# Enabling a payment method

This note is the support procedure for turning on a payment method in Stripe. A payment method is how the customer pays, such as a card. It is not a refund, a dispute, or a payout.

## Dashboard

Enable or manage payment methods from the Payments settings in the Dashboard. Turning a method on makes it available to the integration. It does not charge a customer by itself.

## Extra steps

Some methods need more than the toggle. The Dashboard can ask for business details or limit the method to certain countries. Until those steps are finished, the method stays unavailable.

## Integration

The integration has to request the method. If the Payments settings allow it and the integration never asks for it, customers do not see it at checkout.
