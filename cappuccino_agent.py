import asyncio

from nltk.sentiment import SentimentIntensityAnalyzer


class CappuccinoAgent:
    """Simple agent that generates responses with sentiment awareness."""

    def __init__(self):
        self.sentiment = SentimentIntensityAnalyzer()

    async def detect_sentiment(self, text: str) -> str:
        """Return 'positive', 'negative', or 'neutral' sentiment for text."""
        scores = await asyncio.to_thread(self.sentiment.polarity_scores, text)
        compound = scores.get("compound", 0)
        if compound >= 0.05:
            return "positive"
        if compound <= -0.05:
            return "negative"
        return "neutral"

    async def generate_response(self, text: str) -> str:
        """Generate a basic response incorporating sentiment."""
        sentiment = await self.detect_sentiment(text)
        if sentiment == "negative":
            prefix = "I'm sorry to hear that. "
        elif sentiment == "positive":
            prefix = "That's great! "
        else:
            prefix = ""
        # Placeholder for actual LLM call
        return prefix + text
