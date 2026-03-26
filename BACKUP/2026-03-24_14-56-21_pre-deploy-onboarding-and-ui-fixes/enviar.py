import argparse
import os
from pathlib import Path

import requests
from dotenv import load_dotenv


def normalize_number(number: str) -> str:
    return "".join(ch for ch in (number or "") if ch.isdigit())


def read_numbers_file(file_path: str) -> list[str]:
    numbers: list[str] = []
    for raw_line in Path(file_path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        clean = normalize_number(line)
        if clean:
            numbers.append(clean)
    return numbers


def send_whatsapp_text(access_token: str, phone_number_id: str, to_number: str, message: str) -> tuple[bool, str]:
    url = f"https://graph.facebook.com/v23.0/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": message},
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if 200 <= response.status_code < 300:
            return True, response.text
        return False, f"{response.status_code} - {response.text}"
    except Exception as exc:
        return False, str(exc)


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Enviar mensaje por WhatsApp Cloud API a un número o a una lista.")
    parser.add_argument("--to", help="Número destino en formato internacional, por ejemplo +549261...", default="")
    parser.add_argument("--numbers-file", help="Archivo .txt con un número por línea", default="")
    parser.add_argument("--message", help="Texto del mensaje a enviar", required=True)
    args = parser.parse_args()

    access_token = os.getenv("ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("PHONE_NUMBER_ID", "").strip()
    if not access_token or not phone_number_id:
        print("❌ Faltan ACCESS_TOKEN o PHONE_NUMBER_ID en .env")
        return 1

    numbers: list[str] = []
    if args.to:
        n = normalize_number(args.to)
        if n:
            numbers.append(n)
    if args.numbers_file:
        numbers.extend(read_numbers_file(args.numbers_file))

    numbers = list(dict.fromkeys(numbers))
    if not numbers:
        print("❌ Debes indicar --to o --numbers-file con al menos un número válido.")
        return 1

    print(f"📤 Enviando mensaje a {len(numbers)} número(s)...")
    success = 0
    for number in numbers:
        ok, detail = send_whatsapp_text(access_token, phone_number_id, number, args.message)
        if ok:
            success += 1
            print(f"✅ {number}: enviado")
        else:
            print(f"❌ {number}: {detail}")

    print(f"Resultado: {success}/{len(numbers)} enviados correctamente")
    return 0 if success == len(numbers) else 2


if __name__ == "__main__":
    raise SystemExit(main())