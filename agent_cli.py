import requests
import sys
import base64
import io
from PIL import Image

sys.stdout.reconfigure(encoding='utf-8')


def main() -> None:
    url = "http://163.43.113.161:8000/agent/run"
    query = sys.argv[1] if len(sys.argv) > 1 else input("Query: ")

    res = requests.post(url, json={"query": query})
    res.raise_for_status()
    result = res.json()

    text_output = result.get("text", "")
    if text_output:
        print(text_output)

    images = result.get("images", [])
    if images:
        for i, img_data_uri in enumerate(images):
            try:
                header, encoded = img_data_uri.split(",", 1)
                binary_data = base64.b64decode(encoded)
                image = Image.open(io.BytesIO(binary_data))
                filename = f"generated_image_{i+1}.png"
                image.save(filename)
                print(f"画像{i+1}: {filename} に保存しました。")
            except Exception as e:  # pragma: no cover - manual use
                print(f"画像{i+1}の保存中にエラーが発生しました: {e}")


if __name__ == "__main__":  # pragma: no cover - manual run
    main()
