# PayPal data available to Finance Chat

## Current connection model

The app uses a single server-configured PayPal REST application. The backend reads `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and `PAYPAL_BASE_URL` from `backend/.env`; the configured base URL is restricted in code to `https://api-m.sandbox.paypal.com`. It gets an OAuth `client_credentials` token and refreshes it in process memory shortly before expiry. No PayPal token or credential is sent to Android or Groq.

Android guest tokens authorize requests to this backend, but they do not identify or link a PayPal user. Every guest session currently accesses the same configured Sandbox application's account. Do not describe these records as belonging to the individual guest. Per-user account isolation requires a PayPal user-consent/OAuth linking flow and a durable mapping from the authenticated app user to that user's PayPal authorization; neither exists here.

## Data availability

| Data category | PayPal API and permissions | Backend implementation | Finance Chat access and limits |
|---|---|---|---|
| Account/profile and verification | No account identity/profile endpoint is configured. Client-credentials OAuth is not a user profile consent flow. | Not implemented. `account_id` from the balance response is kept out of Groq context. | Unavailable. Requires a user-authorized Identity/account capability and consent. |
| Balances | `GET /v1/reporting/balances`, scope `https://uri.paypal.com/services/reporting/balances/read`. | Implemented in `paypal_service.get_paypal_balances`. Returns per-currency `total_balance`, `available_balance`, `withheld_balance`, and PayPal refresh timestamps. | Freshly fetched for balance, funds, wallet, and affordability questions. No separate pending-balance field is returned. PayPal says balance records may take up to three hours to appear, so the assistant receives and must report the API timestamp. |
| Transaction history | `GET /v1/reporting/transactions`, scope `https://uri.paypal.com/services/reporting/search/read`. Supports `transaction_info`, `payer_info`, date windows up to 31 days, pages of up to 500, and up to the prior three years. | Implemented with date range, page, transaction-ID and optional payer-info filters. Existing `days` callers remain supported. | Fetched on relevant questions with a 31-day-or-smaller window; chat follows up to 10 pages of 100 and reports whether coverage is complete. It requests non-balance-affecting rows too, so pending/denied informational events can be included. PayPal records can be delayed. |
| Individual transaction details | Transaction Search can filter by transaction ID and return `transaction_info`; `payer_info` is selectively requested for sender questions. | Implemented through the same transaction-search service and route query fields. | Available when within the requested date window. Chat only sends allowlisted fields and redacts email/phone-like text. A recipient's identity is not guaranteed by this integration. |
| Payments and captures | Orders v2 and Payments APIs exist, but no order/capture service or user/account ownership store is configured. | Not implemented as individual resource lookups. Reporting rows may include payment event, reference ID, amount, status, dates, and fee. | Transaction-level payment evidence only. Full order/capture state and authorization/void details are unavailable. |
| Refunds and reversals | No direct refund-resource lookup is configured. Reporting transaction search can return refund/reversal events and statuses. | No dedicated refund service. | Refund/reversal transaction rows can be described when returned by search; direct refund resource state is unavailable. |
| Subscriptions | Subscriptions API exists, but no subscription service, user consent, or subscription ownership records are configured. | Not implemented. Reporting may show subscription-payment events only. | No subscription agreement/status lookup. |
| Payouts | Payouts API exists, but this app has no payout service or payout permissions configured. | Not implemented. Reporting may show payout transaction events only. | No payout batch or recipient resource details. |
| Invoices | Invoicing API exists, but no invoice service or account ownership mapping is configured. | Not implemented. Reporting transactions may expose an invoice ID. | No invoice line items or invoice payment-status lookup. |
| Disputes and chargebacks | Disputes API exists, but this integration has no disputes service or seller-consent/permission configuration. Reporting may show chargeback events. | Not implemented as individual dispute lookups. | Can explain a returned chargeback transaction row; cannot retrieve dispute evidence, messages, or current case status. |

PayPal's transaction search supports only 31 days per request. Chat retrieves multiple pages up to a fixed ten-page bound (1,000 records); it must state when PayPal reports additional pages. The endpoint can search a specific transaction ID when the date window is supplied. It never claims a bounded page is the entire account history.

## Chat data flow

For a balance or PayPal-finance question, `POST /shopping/chat` uses the existing guest-authenticated route, classifies whether it needs balances or transactions, retrieves those records from the existing PayPal service without a balance cache, and passes a minimized structured snapshot to the existing Groq provider. Short follow-up questions inherit the prior user question's data domain. Shopping context and PayPal data remain separate. The backend does not send credentials, access tokens, PayPal account ID, transaction email addresses, or phone numbers to Groq. Transaction notes and subjects are untrusted text.

If PayPal retrieval fails, the route returns an error and does not call Groq with stale or fabricated values. The balance response distinguishes total, available, and withheld values; `pending_balance_available` is false because this API response does not expose a separate pending balance. For an affordability question with an explicit amount and unambiguous currency, the backend compares against the matching available balance using `Decimal` and supplies the result to Groq. For transaction questions it supplies a currency-separated summary of completed payment/withdrawal inflows and outflows, pending amounts, fees, refunds, and largest qualifying payment outflow. It only classifies recognized PayPal event-code and transaction-type pairs; the model is told to repeat supplied deterministic totals and disclose incomplete page coverage. Amount sign alone is never used to classify a transaction.

The backend guest-session store is process-local, and the PayPal application token is shared by the backend process. This is suitable only for the current single-account Sandbox demo. It is not safe to treat guest sessions as independent PayPal accounts or to deploy it as a multi-user personal-finance service without account linking and durable authorization isolation.

## Official API references

- [PayPal List all balances](https://developer.paypal.com/api/transaction-search/v1/balances-get/)
- [PayPal List transactions](https://developer.paypal.com/api/transaction-search/v1/search-get)
- [PayPal transaction event codes](https://developer.paypal.com/docs/transaction-search/transaction-event-codes/)
- [PayPal current REST API resources](https://developer.paypal.com/api/rest/current-resources/)
- [PayPal REST API authentication](https://developer.paypal.com/api/make-api-requests/)
