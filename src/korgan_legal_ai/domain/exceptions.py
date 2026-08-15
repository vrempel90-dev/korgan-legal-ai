class ClarificationRequired(ValueError):
    def __init__(self, questions: list[str]):
        self.questions = questions
        super().__init__("Clarification required: " + "; ".join(questions))


class LegalQABlocked(RuntimeError):
    pass
