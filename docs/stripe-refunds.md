# Refunding a customer

This note is the support procedure for refunding a Stripe charge. It applies only to payments that are not in dispute.

## Amount

The usual refund is the full charge. A smaller amount is a partial refund.

## Timing

A refund takes 5 to 10 days to appear on the customer's account. After it is sent, the window to cancel it is very short. Try the steps in test mode before refunding a live charge.

## Dashboard

Find the charge on the Transactions page. Open the menu beside the charge and choose Refund payment, or open the charge and use the Refund button at the top right. Leave the amount as the full charge, or enter a smaller amount. Choose a reason. The reason Other requires a note stored with the refund. Then click Refund.

## API

Create a refund and include the charge ID. Include an amount only for a partial refund. If the amount is left out, the full charge is refunded.

## Test mode

From the account picker at the upper left of the Dashboard, choose Switch to sandbox, then Test mode. Test mode uses the test API key. It does not process a real charge or change a live customer.
