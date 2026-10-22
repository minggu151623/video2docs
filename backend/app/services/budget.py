from app.core.errors import AppError


def normalized_usage(raw, output_includes_thinking=False):
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raw = raw.model_dump(exclude_none=True)
    output, thought = raw.get("total_output_tokens"), raw.get("total_thought_tokens")
    billable = (
        output
        if output_includes_thinking
        else (output + thought if output is not None and thought is not None else None)
    )
    return {
        "input_tokens": raw.get("total_input_tokens"),
        "output_tokens": raw.get("total_output_tokens"),
        "thinking_tokens": raw.get("total_thought_tokens"),
        "billable_output_tokens": billable,
        "output_includes_thinking": output_includes_thinking,
        "raw": raw,
    }


def cost(usage, price, today):
    if not price or not price.effective_from <= today <= price.effective_to or not usage:
        return None
    if usage.get("input_tokens") is None or usage.get("billable_output_tokens") is None:
        return None
    return (
        usage["input_tokens"] * price.input_rate + usage["billable_output_tokens"] * price.output_rate
    ) / 1_000_000


def check_budget(attempts, remaining_chunks, cap, known_cost, next_estimate, budget, allow_unknown):
    if attempts + remaining_chunks > cap:
        raise AppError("ATTEMPT_LIMIT", "Không còn đủ lượt gọi cho các đoạn còn lại.", 422)
    if next_estimate is None and not allow_unknown:
        raise AppError("COST_UNKNOWN", "Cần chủ động chấp nhận chi phí chưa xác định.", 422)
    if known_cost > budget or (next_estimate is not None and known_cost + next_estimate > budget):
        raise AppError("BUDGET_EXCEEDED", "Đã chạm ngân sách mềm của job.", 422)
