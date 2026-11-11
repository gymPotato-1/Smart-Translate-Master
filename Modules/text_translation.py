
import requests


def translate_text(
    text,
    translator_key,
    translator_region,
    source_language=None,
    target_language="zh-Hans",
):
    url = (
        "https://api.cognitive.microsofttranslator.com"
        "/translate"
    )

    params = {
        "api-version": "3.0",
        "to": target_language,
    }

    # Azure Translator can detect source language
    # when the 'from' parameter is omitted.
    if source_language:
        params["from"] = source_language.split("-")[0]

    headers = {
        "Ocp-Apim-Subscription-Key": translator_key,
        "Ocp-Apim-Subscription-Region": translator_region,
        "Content-Type": "application/json",
    }

    response = requests.post(
        url,
        params=params,
        headers=headers,
        json=[{"text": text}],
        timeout=15,
    )

    response.raise_for_status()

    data = response.json()

    return data[0]["translations"][0]["text"]
