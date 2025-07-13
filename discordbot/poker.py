
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass
from typing import List, Optional
import logging

logger = logging.getLogger(__name__)

import discord
from treys import Card, Deck, Evaluator


# Basic text emoji for card suits
SUIT_MAP = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
RANKS = "23456789TJQKA"

def card_to_emoji(card: int) -> str:
    rank = Card.get_rank_int(card)
    suit_char = Card.INT_SUIT_TO_CHAR_SUIT[Card.get_suit_int(card)]
    return f"{RANKS[rank]}{SUIT_MAP[suit_char]}"


def format_hand(cards: List[int]) -> str:
    return " ".join(card_to_emoji(c) for c in cards)


@dataclass
class Player:
    user: discord.abc.User
    chips: int = 50000
    hand: List[int] | None = None
    bet: int = 0
    acted: bool = False
    folded: bool = False


class PokerMatch:
    small_blind = 500
    big_blind = 1000

    def __init__(self, p1: discord.abc.User, p2: discord.abc.User, bot_user: discord.abc.User):
        self.players = [Player(p1), Player(p2)]
        self.bot_user = bot_user
        self.evaluator = Evaluator()
        self.dealer = 0
        self.deck = Deck()
        self.board: List[int] = []
        self.pot = 0
        self.current_bet = 0
        self.turn = 0
        self.stage = ""
        self.message: Optional[discord.Message] = None
        self.log_lines: List[str] = []
        self.final_lines: List[str] = []

    def _log(self, text: str):
        self.log_lines.append(text)
        joined = "\n".join(self.log_lines)
        while len(joined) > 1000:
            self.log_lines.pop(0)
            joined = "\n".join(self.log_lines)

    async def start(self, channel: discord.abc.Messageable):
        self.channel = channel
        await self._start_hand()

    async def _start_hand(self):
        self.deck = Deck()
        self.board = []
        self.final_lines = []
        self._log("--- New hand ---")
        for p in self.players:
            p.hand = self.deck.draw(2)
            p.bet = 0
            p.acted = False
            p.folded = False
        self.pot = 0
        self.current_bet = 0
        self.stage = "preflop"
        self.dealer ^= 1  # alternate dealer
        sb = self.dealer
        bb = 1 - self.dealer
        await self._send_hands()
        self._post_blind(sb, self.small_blind)
        self._post_blind(bb, self.big_blind)
        self.turn = sb
        await self._update_message(initial=True)
        if self._current_player_is_bot():
            await self._bot_action()

    def _post_blind(self, idx: int, amount: int):
        p = self.players[idx]
        blind = min(amount, p.chips)
        p.chips -= blind
        p.bet = blind
        self.pot += blind
        self.current_bet = max(self.current_bet, blind)
        self._log(f"{p.user.display_name} posts {blind}")

    async def _send_hands(self):
        for p in self.players:
            # ClientUser (the bot itself) does not implement `create_dm`,
            # so skip DMing it.  We also avoid calling create_dm on any
            # object lacking the method just in case.
            if p.user.id == self.bot_user.id or not hasattr(p.user, "create_dm"):
                continue
            try:
                dm = await p.user.create_dm()
                await dm.send(f"Your hand: {format_hand(p.hand)}")
            except discord.Forbidden as e:
                logger.warning("Failed to send hand to %s: %s", p.user, e)
                await self.channel.send(
                    f"{p.user.mention} さん、DM がオフになっているためハンドを送れませんでした。"
                )
            except discord.HTTPException as e:
                logger.error("HTTP error when sending hand to %s: %s", p.user, e)
                await self.channel.send(
                    f"{p.user.mention} さんへのDM送信でエラーが発生しました。"
                )

    def _current_player_is_bot(self) -> bool:
        return self.players[self.turn].user.id == self.bot_user.id

    def _all_players_allin(self) -> bool:
        return all(pl.chips == 0 or pl.folded for pl in self.players)

    def _any_player_allin(self) -> bool:
        return any(pl.chips == 0 and not pl.folded for pl in self.players)

    def _next_turn(self):
        self.turn ^= 1

    async def player_action(self, user: discord.abc.User, action: str, raise_to: int | None = None):
        if user.id != self.players[self.turn].user.id:
            return
        p = self.players[self.turn]
        opp = self.players[self.turn ^ 1]

        # If the opponent is already all-in, further raises are not allowed.
        if opp.chips == 0 and action in {"raise", "allin"}:
            action = "call"

        if action == "fold":
            p.folded = True
            self._log(f"{p.user.display_name} folds")
            await self._finish_hand(winner=opp)
            return

        to_call = self.current_bet - p.bet
        if action == "call":
            amount = min(to_call, p.chips)
            p.chips -= amount
            p.bet += amount
            self.pot += amount
            p.acted = True
            if amount < to_call:
                # Player called all-in for less; refund the excess to opponent
                diff = to_call - amount
                opp.bet -= diff
                opp.chips += diff
                self.pot -= diff
                self.current_bet = p.bet
                self._log(f"{opp.user.display_name} gets back {diff}")
            self._log(f"{p.user.display_name} calls {amount}")
        elif action == "check":
            p.acted = True
            self._log(f"{p.user.display_name} checks")
        elif action == "raise":
            if raise_to is None:
                raise_to = self.current_bet + self.big_blind
            amount = min(raise_to - p.bet, p.chips)
            p.chips -= amount
            p.bet += amount
            self.pot += amount
            self.current_bet = p.bet
            p.acted = True
            opp.acted = False
            self._log(f"{p.user.display_name} raises to {p.bet}")
            if p.chips == 0:
                await self._send_effect(f"{p.user.display_name} ALL-IN! 💥")
        elif action == "allin":
            await self.player_action(user, "raise", p.bet + p.chips)
            return

        if p.chips == 0 and not p.folded:
            p.acted = True
        if opp.folded:
            await self._finish_hand(winner=p)
            return
        if p.acted and opp.acted and p.bet == opp.bet:
            await self._next_stage()
            if self._any_player_allin():
                await self._auto_runout()
                return
        else:
            self._next_turn()
        await self._update_message()
        if self._current_player_is_bot():
            await self._bot_action()

    async def _next_stage(self):
        for pl in self.players:
            pl.bet = 0
            pl.acted = False
        self.current_bet = 0
        if self.stage == "preflop":
            self.stage = "flop"
            self.board.extend(self.deck.draw(3))
            self.turn = 1 - self.dealer
            self._log(f"Flop: {format_hand(self.board)}")
        elif self.stage == "flop":
            self.stage = "turn"
            self.board.extend(self.deck.draw(1))
            self.turn = 1 - self.dealer
            self._log(f"Turn: {format_hand(self.board)}")
        elif self.stage == "turn":
            self.stage = "river"
            self.board.extend(self.deck.draw(1))
            self.turn = 1 - self.dealer
            self._log(f"River: {format_hand(self.board)}")
        elif self.stage == "river":
            await self._showdown()
            return

    async def _showdown(self):
        p0, p1 = self.players
        self._log(
            f"Showdown! {p0.user.display_name}: {format_hand(p0.hand)} vs "
            f"{p1.user.display_name}: {format_hand(p1.hand)}"
        )
        s0 = self.evaluator.evaluate(p0.hand, self.board)
        s1 = self.evaluator.evaluate(p1.hand, self.board)
        name0 = self.evaluator.class_to_string(self.evaluator.get_rank_class(s0))
        name1 = self.evaluator.class_to_string(self.evaluator.get_rank_class(s1))
        self.final_lines = [
            f"{p0.user.display_name}: {format_hand(p0.hand)} ({name0})",
            f"{p1.user.display_name}: {format_hand(p1.hand)} ({name1})",
        ]
        if s0 < s1:
            await self._finish_hand(winner=p0)
        elif s1 < s0:
            await self._finish_hand(winner=p1)
        else:
            half = self.pot // 2
            remainder = self.pot % 2
            p0.chips += half
            p1.chips += half
            if remainder:
                self.players[1 - self.dealer].chips += remainder
            self._log("It's a tie!")
            await self._update_message()
            await self._check_game_end()

    async def _finish_hand(self, winner: Player):
        winner.chips += self.pot
        self._log(
            f"{winner.user.display_name} wins {self.pot} 💰 with board {format_hand(self.board)}"
        )
        await self._update_message()
        await self._check_game_end()

    async def _check_game_end(self):
        losers = [p.user.display_name for p in self.players if p.chips <= 0]
        if losers:
            names = ", ".join(losers)
            self._log(f"Game over! {names} ran out of chips.")
            await self._update_message()
            return
        await self._start_hand()

    async def _send_effect(self, text: str):
        self._log(text)
        await self._update_message()

    async def _bot_action(self):
        await asyncio.sleep(1)
        p = self.players[self.turn]
        opp = self.players[self.turn ^ 1]
        to_call = self.current_bet - p.bet

        # Estimate win probability and expected hand strength for decision making
        rates, avg_rank = self._calc_win_rates_and_strength(300)
        win_rate = rates[self.turn]
        board_best = self._calc_board_best_class()

        action = "check"
        raise_to = None

        strong_hand = avg_rank <= max(5, board_best + 1)  # straight or near nuts

        if opp.chips == 0:
            # Opponent is all-in; raising makes no sense
            action = "call" if to_call > 0 else "check"
        elif to_call > 0:
            if win_rate < 0.4:
                action = "fold"
            elif win_rate < 0.6 and not strong_hand:
                action = "call"
            else:
                action = "raise"
                raise_to = min(self.current_bet + self.big_blind, p.bet + p.chips)
        else:
            if win_rate > 0.65 or strong_hand:
                action = "raise"
                raise_to = self.current_bet + self.big_blind
            else:
                action = "check"

        if action == "raise" and raise_to is not None:
            await self.player_action(p.user, action, raise_to)
        else:
            await self.player_action(p.user, action)

    def _calc_win_rates(self, iterations: int = 500) -> List[float]:
        known = self.board + [c for pl in self.players for c in pl.hand]
        deck_cards = [c for c in Deck().cards if c not in known]
        wins = [0, 0]
        ties = 0
        for _ in range(iterations):
            random.shuffle(deck_cards)
            board = list(self.board)
            board.extend(deck_cards[: 5 - len(board)])
            s0 = self.evaluator.evaluate(self.players[0].hand, board)
            s1 = self.evaluator.evaluate(self.players[1].hand, board)
            if s0 < s1:
                wins[0] += 1
            elif s1 < s0:
                wins[1] += 1
            else:
                ties += 1
        total = iterations
        return [
            (wins[0] + ties / 2) / total,
            (wins[1] + ties / 2) / total,
        ]

    def _calc_win_rates_and_strength(self, iterations: int = 300) -> tuple[List[float], float]:
        known = self.board + [c for pl in self.players for c in pl.hand]
        deck_cards = [c for c in Deck().cards if c not in known]
        wins = [0, 0]
        ties = 0
        rank_sum = 0
        bot_idx = self.turn
        for _ in range(iterations):
            random.shuffle(deck_cards)
            board = list(self.board)
            board.extend(deck_cards[: 5 - len(board)])
            s0 = self.evaluator.evaluate(self.players[0].hand, board)
            s1 = self.evaluator.evaluate(self.players[1].hand, board)
            if s0 < s1:
                wins[0] += 1
            elif s1 < s0:
                wins[1] += 1
            else:
                ties += 1
            bot_score = s0 if bot_idx == 0 else s1
            rank_sum += self.evaluator.get_rank_class(bot_score)
        total = iterations
        rates = [
            (wins[0] + ties / 2) / total,
            (wins[1] + ties / 2) / total,
        ]
        avg_rank = rank_sum / total
        return rates, avg_rank

    def _format_win_rate(self, rates: List[float]) -> str:
        p0, p1 = self.players
        return (
            f"Win odds: {p0.user.display_name} {rates[0]*100:.1f}% - "
            f"{p1.user.display_name} {rates[1]*100:.1f}%"
        )

    def _calc_board_best_class(self) -> int:
        if len(self.board) < 5:
            return 9  # High Card as default when board is incomplete
        deck_cards = [c for c in Deck().cards if c not in self.board]
        best = 7462
        from itertools import combinations
        for c1, c2 in combinations(deck_cards, 2):
            score = self.evaluator.evaluate([c1, c2], self.board)
            if score < best:
                best = score
        return self.evaluator.get_rank_class(best)

    async def _auto_runout(self):
        p0, p1 = self.players
        self._log(
            f"All-in! {p0.user.display_name}: {format_hand(p0.hand)} vs "
            f"{p1.user.display_name}: {format_hand(p1.hand)}"
        )
        # Immediately show win odds at the moment of showdown
        rates = self._calc_win_rates()
        self._log(self._format_win_rate(rates))
        await self._update_message()
        while self.stage != "river":
            await asyncio.sleep(1)
            await self._next_stage()
            rates = self._calc_win_rates()
            self._log(self._format_win_rate(rates))
            await self._update_message()
        await asyncio.sleep(1)
        await self._next_stage()

    async def _update_message(self, initial: bool = False):
        desc = "\n".join(self.log_lines) if self.log_lines else ""
        embed = discord.Embed(description=desc)

        info = f"Pot: 💰{self.pot}\n"
        info += f"Board: {format_hand(self.board)}\n"
        if self.final_lines:
            info += "\n".join(self.final_lines) + "\n"
        info += "\n".join(
            f"{pl.user.display_name}: 💰{pl.chips}  Bet {pl.bet}" for pl in self.players
        )
        if not initial:
            info += f"\nWaiting for {self.players[self.turn].user.display_name}"
        embed.add_field(name="Game", value=info, inline=False)
        if self.message is None:
            self.message = await self.channel.send(embed=embed)
        else:
            try:
                await self.message.edit(embed=embed)
            except discord.HTTPException:
                self.message = await self.channel.send(embed=embed)


class PokerView(discord.ui.View):
    def __init__(self, game: PokerMatch):
        super().__init__(timeout=None)
        self.game = game

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True

    async def _act(self, interaction: discord.Interaction, action: str, raise_to: int | None = None):
        await interaction.response.defer()
        await self.game.player_action(interaction.user, action, raise_to)

    @discord.ui.button(label="Fold", style=discord.ButtonStyle.danger)
    async def fold(self, interaction: discord.Interaction, _):
        await self._act(interaction, "fold")

    @discord.ui.button(label="Check/Call", style=discord.ButtonStyle.secondary)
    async def call(self, interaction: discord.Interaction, _):
        await self._act(interaction, "call" if self.game.current_bet > self.game.players[self.game.turn].bet else "check")

    @discord.ui.button(label="Raise +1BB", style=discord.ButtonStyle.primary)
    async def raise_small(self, interaction: discord.Interaction, _):
        amount = self.game.big_blind
        await self._act(interaction, "raise", self.game.current_bet + amount)

    @discord.ui.button(label="Raise Pot", style=discord.ButtonStyle.primary)
    async def raise_big(self, interaction: discord.Interaction, _):
        amount = self.game.pot if self.game.pot else self.game.big_blind * 5
        await self._act(interaction, "raise", self.game.current_bet + amount)

    @discord.ui.button(label="All-in", style=discord.ButtonStyle.success)
    async def allin(self, interaction: discord.Interaction, _):
        await self._act(interaction, "allin")

