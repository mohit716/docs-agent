# docs-agent operator notes

These notes describe the personal docs-agent setup. Answers about the bucket, knowledge base, and guardrail come from this file.

## Bucket

Source documents are stored in the S3 bucket docs-agent-mohit716 in US East (N. Virginia), us-east-1. The sample office guide is office-guide.md in that bucket.

## Knowledge base

The managed knowledge base is named docs-agent. Its ID is HR5D1WUZG4. It reads documents from s3://docs-agent-mohit716/ and returns matching passages when search_docs is called.

## Guardrail

The guardrail is named docs-agent-guardrail. Its ID is d4kbabpmm9jf and the published version is 1. Off-topic questions are blocked with the message "Sorry, the model cannot answer this question." Email addresses, phone numbers, names, and street addresses are masked. A reply that is not supported by the retrieved passage is blocked.

## What it answers

The agent answers questions that are covered by the retrieved documents, including these operator notes, the Northwind office guide, the Stripe refund procedure in stripe-refunds.md, the dispute procedure in stripe-disputes.md, the payout procedure in stripe-payouts.md, the payment method procedure in stripe-payment-methods.md, and the unrecognized charge note in stripe-unrecognized-charge.md. Questions outside those documents are refused.

## How to refresh

Upload the changed file to the bucket docs-agent-mohit716. Open the docs-agent knowledge base, select the S3 data source, and click Sync. Ask a question only after the sync finishes.
