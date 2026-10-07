from pathlib import Path

import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv

from agent.config import load_settings
from agent.loop import run_turn
from agent.tools import NotesStore, build_tools

ROOT = Path(__file__).resolve().parent


def main() -> None:
    load_dotenv(ROOT / ".env")
    settings = load_settings()
    client = boto3.client("bedrock-runtime", region_name=settings.region)
    tools = build_tools(NotesStore(ROOT / "data" / "notes.json"))
    messages: list[dict] = []

    print(f"Bedrock agent ({settings.model_id}, {settings.region}).")
    print("Commands: /reset clears the chat, /exit quits.")

    while True:
        try:
            user_text = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return

        if not user_text:
            continue
        if user_text.lower() in {"/exit", "/quit"}:
            return
        if user_text.lower() == "/reset":
            messages.clear()
            print("Chat cleared.")
            continue

        start = len(messages)
        messages.append({"role": "user", "content": [{"text": user_text}]})
        try:
            reply = run_turn(
                client,
                settings,
                messages,
                tools,
                on_tool=lambda name: print(f"  · {name}"),
            )
        except NoCredentialsError:
            del messages[start:]
            print(
                "No AWS credentials found. Run `aws configure`, or set "
                "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY in .env."
            )
            continue
        except ClientError as exc:
            del messages[start:]
            print(friendly_error(exc))
            continue

        print(f"\nAgent: {reply or '(no reply)'}")


def friendly_error(exc: ClientError) -> str:
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    message = error.get("Message", str(exc))
    if code in {"AccessDeniedException", "AccessDenied"}:
        return (
            "Bedrock denied this call. In the Bedrock console, enable "
            f"{load_settings().model_id} in {load_settings().region}, and allow "
            f"bedrock:InvokeModel for your IAM user. ({message})"
        )
    if code == "ValidationException":
        return (
            "Bedrock rejected the request. Check BEDROCK_MODEL_ID and AWS_REGION. "
            f"({message})"
        )
    if code == "ThrottlingException":
        return "Bedrock throttled the request. Wait a moment and try again."
    if code in {
        "UnrecognizedClientException",
        "ExpiredTokenException",
        "InvalidSignatureException",
    }:
        return f"AWS credentials were rejected. ({message})"
    return f"Bedrock error {code}: {message}"


if __name__ == "__main__":
    main()
