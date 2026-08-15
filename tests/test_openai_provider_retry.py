from types import SimpleNamespace

from pydantic import BaseModel, ValidationError

from korgan_legal_ai.llm.openai_provider import OpenAIProvider


class ResultSchema(BaseModel):
    value: int


class FakeResponses:
    def __init__(self) -> None:
        self.calls = 0
        self.inputs = []
        self.kwargs = []

    def parse(self, **kwargs):
        self.calls += 1
        self.inputs.append(kwargs["input"])
        self.kwargs.append(kwargs)
        if self.calls == 1:
            ResultSchema.model_validate({"value": "not-an-integer"})
        return SimpleNamespace(output_parsed=ResultSchema(value=7), output=[])


class FakeClient:
    def __init__(self) -> None:
        self.responses = FakeResponses()


def test_validation_error_retries_once_without_exposing_user_text(caplog):
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = FakeClient()
    secret_user_text = "PRIVATE-CASE-TEXT-123"

    result = provider.parse(
        model="test-model",
        system="system",
        user=secret_user_text,
        schema=ResultSchema,
    )

    assert result.value == 7
    assert provider.client.responses.calls == 2
    assert "STRUCTURED OUTPUT CORRECTION" in provider.client.responses.inputs[1][0]["content"]
    assert all(call["store"] is False for call in provider.client.responses.kwargs)
    assert secret_user_text not in caplog.text
    assert "ResultSchema" in caplog.text


def test_validation_signature_contains_only_locations_and_types():
    try:
        ResultSchema.model_validate({"value": "SECRET-VALUE"})
    except ValidationError as exc:
        signature = OpenAIProvider._validation_signature(exc)
    else:
        raise AssertionError("ValidationError expected")

    assert "value" in signature
    assert "SECRET-VALUE" not in signature
