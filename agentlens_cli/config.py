"""Pricing configuration for cost attribution."""


class CostModel:
    """Token pricing model. All prices are per 1M tokens."""

    def __init__(self, input_price: float = 2.4, output_price: float = 8.0):
        self.input_price = input_price
        self.output_price = output_price

    def input_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.input_price

    def output_cost(self, tokens: int) -> float:
        return (tokens / 1_000_000) * self.output_price

    def total_cost(self, tokens_in: int, tokens_out: int) -> float:
        return self.input_cost(tokens_in) + self.output_cost(tokens_out)

    def to_dict(self) -> dict:
        return {
            "input_price_per_1m": self.input_price,
            "output_price_per_1m": self.output_price,
            "currency": "CNY",
            "note": "estimate — configurable pricing model",
        }


# Default instance
DEFAULT_COST_MODEL = CostModel()