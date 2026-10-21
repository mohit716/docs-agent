import argparse
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from agent.config import load_settings
from agent.tools import DocIndex


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    parser = argparse.ArgumentParser(description="Index Markdown and text documents.")
    parser.add_argument("--docs", type=Path, default=Path("docs"))
    args = parser.parse_args()

    settings = load_settings()
    if settings.search_backend != "opensearch":
        raise SystemExit("Set SEARCH_BACKEND=opensearch before indexing documents.")

    from opensearchpy import OpenSearch

    auth = (
        (settings.opensearch_username, settings.opensearch_password)
        if settings.opensearch_username
        else None
    )
    client = OpenSearch(
        hosts=[settings.opensearch_url],
        http_auth=auth,
        use_ssl=settings.opensearch_url.startswith("https://"),
        verify_certs=settings.opensearch_verify_certs,
        ssl_assert_hostname=settings.opensearch_verify_certs,
        ssl_show_warn=settings.opensearch_verify_certs,
    )
    client.indices.create(
        index=settings.opensearch_index,
        body={
            "mappings": {
                "properties": {
                    "file_name": {"type": "keyword"},
                    "section": {"type": "keyword"},
                    "path": {"type": "keyword"},
                    "text": {"type": "text"},
                    "updated_at": {"type": "date"},
                }
            }
        },
        ignore=400,
    )

    indexed = 0
    for file_name, text in DocIndex(args.docs)._chunks():
        section = text.splitlines()[0].lstrip("# ").strip()
        client.index(
            index=settings.opensearch_index,
            body={
                "file_name": file_name,
                "section": section,
                "path": str(args.docs / file_name),
                "text": text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        indexed += 1
    client.indices.refresh(index=settings.opensearch_index)
    print(f"Indexed {indexed} document sections into {settings.opensearch_index}.")


if __name__ == "__main__":
    main()
