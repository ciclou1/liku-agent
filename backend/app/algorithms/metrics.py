from collections.abc import Sequence


def wape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual and predicted must have the same non-empty length")
    denominator = sum(abs(value) for value in actual)
    return 0.0 if denominator == 0 else sum(abs(a - p) for a, p in zip(actual, predicted)) / denominator


def mape(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) != len(predicted) or not actual:
        raise ValueError("actual and predicted must have the same non-empty length")
    valid = [(a, p) for a, p in zip(actual, predicted) if a != 0]
    return 0.0 if not valid else sum(abs(a - p) / abs(a) for a, p in valid) / len(valid)


def directional_accuracy(actual: Sequence[float], predicted: Sequence[float]) -> float:
    if len(actual) != len(predicted) or len(actual) < 2:
        raise ValueError("at least two aligned values are required")
    correct = sum((actual[i] - actual[i - 1]) * (predicted[i] - predicted[i - 1]) >= 0 for i in range(1, len(actual)))
    return correct / (len(actual) - 1)

