"""KORGAN claim house style derived from the user's real Kazakhstan claim exemplars.

Only drafting style and document organization are carried over. Names, identifiers,
addresses, amounts, case facts and potentially stale legal citations from exemplars are
never copied. Current source-bound law and existing fact locks remain authoritative.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from korgan.docx_blocks import AutoNumberedList, Block, Prose


CLAIM_EXEMPLAR_STYLE = """
ВНУТРЕННИЙ СТИЛЕВОЙ СТАНДАРТ KORGAN — ИСКИ ПО ОБРАЗЦАМ ПРАКТИКУЮЩИХ ЮРИСТОВ РК.
Это правила СТИЛЯ И СТРУКТУРЫ, а не факты дела и не источник права.

1. Внешне и по тону документ должен быть похож на реальный иск практикующего юриста Республики Казахстан, а не на AI-аналитику или юридическую консультацию.
2. Заголовок для русского иска: первая строка «И С К», следующая строка — короткий предмет, например «о взыскании суммы задолженности и неустойки». Не используй громоздкий маркетинговый заголовок.
3. После шапки сразу переходи к связному изложению. Не создавай искусственные разделы «Фактические обстоятельства», «Правовое обоснование», «Юридический анализ», «Позиция истца».
4. Факты излагай хронологически: правоотношение/договор -> существенное условие -> исполнение истцом -> нарушение ответчиком -> досудебные действия -> расчет -> судебные расходы, если они реально подтверждены материалами.
5. Когда конкретная VERIFIED-норма непосредственно объясняет юридическое значение факта, используй традиционный судебный переход «Согласно...», «В соответствии...», «Статьей ... установлено...», но не цитируй норму ради объема. Номер и смысл статьи — только из VERIFIED.
6. Ключевые условия договора или расписки можно кратко воспроизводить в тексте, только если они есть в материалах пользователя. Не выдумывай номер пункта или дословную цитату.
7. Для денежных требований показывай понятный расчет отдельными абзацами: исходная сумма, ставка/основание, период, формула и итог — только когда эти данные подтверждены. Не прячь расчет в общих словах.
8. Досудебную претензию, уведомление, оплату госпошлины, договор с представителем и расходы на представителя описывай только при наличии соответствующих материалов. Ничего не добавляй «как обычно бывает».
9. Перед просительной частью сделай короткий вывод о том, почему заявленные требования следуют из установленных обстоятельств и VERIFIED-норм. Не повторяй весь иск второй раз.
10. Просительная часть должна выглядеть по-судебному: «На основании вышеизложенного ... ПРОШУ СУД:» и далее короткие, самостоятельные, нумерованные требования. Каждое денежное требование — отдельным пунктом с точной суммой.
11. После требований — «Приложения:» и только фактически имеющиеся/указанные пользователем документы. Не придумывай количество экземпляров.
12. Язык: деловой, прямой, уверенный, без чатовых оборотов, советов пользователю, длинных оговорок и лишних повторов. Термины «Истец», «Ответчик», «Договор» используй последовательно.
13. Не копируй из эталонов орфографические ошибки, персональные данные, старые ставки госпошлины, устаревшие статьи или сомнительные формулировки. Текущая source-bound проверка KORGAN всегда важнее текста эталона.
14. Если фактов недостаточно для сильной формулировки — не заполняй пробел правдоподобным текстом; сохрани существующий fail-closed подход KORGAN.
""".strip()


def with_claim_exemplar_style(case_context: str) -> str:
    """Append non-factual house-style instructions to the drafting context only."""
    marker = "ВНУТРЕННИЙ СТИЛЕВОЙ СТАНДАРТ KORGAN — ИСКИ ПО ОБРАЗЦАМ"
    if marker in (case_context or ""):
        return case_context
    return f"{case_context}\n\n---\n{CLAIM_EXEMPLAR_STYLE}"


def exemplar_body_blocks(draft: Any, *, kk: bool) -> list[Block]:
    """Render a traditional pleading body without artificial AI section headings."""
    # Kazakh rendering keeps the canonical renderer because the supplied exemplars
    # are Russian-language pleadings and should not silently define KK legal style.
    if kk:
        from korgan.claim_docx import _body_blocks as current
        if getattr(current, "_korgan_exemplar_body", False):
            # Defensive recursion escape; installer stores the original separately.
            from korgan.claim_exemplar_style import _ORIGINAL_BODY_BLOCKS
            return _ORIGINAL_BODY_BLOCKS(draft, kk=kk)
        return current(draft, kk=kk)

    blocks: list[Block] = [Prose(fact) for fact in draft.facts]
    # Real exemplars integrate law into the narrative instead of placing it under
    # a generic «Правовое обоснование» heading.
    blocks.extend(Prose(basis) for basis in draft.legal_basis)
    if draft.late_interest:
        blocks.append(Prose(draft.late_interest))
    blocks.append(Prose("На основании вышеизложенного ПРОШУ СУД:"))
    blocks.append(AutoNumberedList(list(draft.requests)))
    blocks.append(Prose("Приложения:"))
    blocks.append(AutoNumberedList(list(draft.attachments), restart=True))
    return blocks


_ORIGINAL_BODY_BLOCKS: Callable[..., list[Block]] | None = None
_INSTALLED = False


def install_claim_exemplar_style() -> None:
    """Install drafting-style and Word-body hooks without changing legal research."""
    global _INSTALLED, _ORIGINAL_BODY_BLOCKS
    if _INSTALLED:
        return

    from korgan import claim_docx
    from korgan import fast_professional_litigation as litigation

    original_draft: Callable[..., Awaitable[Any]] = litigation.FastProfessionalLitigationService.draft_claim
    if not getattr(original_draft, "_korgan_exemplar_style", False):
        async def styled_draft(self: Any, case_context: str, research: Any, language: str = "ru") -> Any:
            return await original_draft(self, with_claim_exemplar_style(case_context), research, language=language)

        styled_draft._korgan_exemplar_style = True  # type: ignore[attr-defined]
        litigation.FastProfessionalLitigationService.draft_claim = styled_draft

    current_body = claim_docx._body_blocks
    if not getattr(current_body, "_korgan_exemplar_body", False):
        _ORIGINAL_BODY_BLOCKS = current_body

        def rendered(draft: Any, *, kk: bool) -> list[Block]:
            if kk:
                assert _ORIGINAL_BODY_BLOCKS is not None
                return _ORIGINAL_BODY_BLOCKS(draft, kk=kk)
            return exemplar_body_blocks(draft, kk=kk)

        rendered._korgan_exemplar_body = True  # type: ignore[attr-defined]
        claim_docx._body_blocks = rendered

    _INSTALLED = True
