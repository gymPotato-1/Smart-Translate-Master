
import requests


def translate_text(text, key, region):
    url = "https://api.cognitive.microsofttranslator.com/translate"

    params = {
        "api-version": "3.0",
        "from": "en",
        "to": "zh-Hans",
    }

    headers = {
        "Ocp-Apim-Subscription-Key": key,
        "Content-Type": "application/json",
    }

    if region:
        headers["Ocp-Apim-Subscription-Region"] = region

    response = requests.post(
        url,
        params=params,
        headers=headers,
        json=[{"Text": text}],
        timeout=15,
    )

    response.raise_for_status()

    return response.json()[0]["translations"][0]["text"]
