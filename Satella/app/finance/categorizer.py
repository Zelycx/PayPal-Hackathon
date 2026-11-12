from app.database.models import Transaction

_RULES = {
    "Food": ("grocery", "market", "restaurant", "cafe", "coffee", "lunch", "food", "noodle"),
    "Transportation": ("train", "bus", "taxi", "transit", "fuel", "grab", "fare"),
    "Shopping": ("store", "shop", "keyboard", "clothing", "purchase"),
    "Entertainment": ("stream", "movie", "game", "music"),
    "Education": ("book", "course", "tuition"),
    "Bills": ("electric", "power", "internet", "water", "cloud", "phone"),
    "Health": ("clinic", "pharmacy", "hospital", "doctor"),
    "Income": ("salary", "payroll", "freelance", "payment", "income"),
    "Transfers": ("transfer", "own accounts"),
}


def categorize(description: str, merchant: str | None = None) -> tuple[str, str]:
    text = f"{description} {merchant or ''}".casefold()
    for category, words in _RULES.items():
        if any(word in text for word in words):
            return category, "rule"
    return "Other", "fallback"


def suggest_transaction_category(transaction: Transaction) -> dict[str, str]:
    category, method = categorize(transaction.description, transaction.merchant)
    return {"suggested_category": category, "method": method, "current_category": transaction.category}
