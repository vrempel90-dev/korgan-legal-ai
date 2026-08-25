from __future__ import annotations


def test_safe_installer_enables_only_external_only_repair_skip(monkeypatch):
    from korgan import production_cost_speed_optimizer_safe as safe
    from korgan.legal import corpus_refresh

    calls: list[str] = []

    monkeypatch.setattr(safe, "_INSTALLED", False)
    monkeypatch.setattr(
        safe.optimizer,
        "_progressive_refresh_factory",
        lambda current, loader: current,
    )
    monkeypatch.setattr(safe.optimizer, "_install_research_scope_optimizer", lambda: calls.append("scope"))
    monkeypatch.setattr(safe.optimizer, "_install_rag_search_context_optimizer", lambda: calls.append("rag"))
    monkeypatch.setattr(safe, "_install_safe_futile_repair_skip", lambda: calls.append("repair-skip"))
    monkeypatch.setattr(safe.optimizer, "_install_economic_court_registry", lambda: calls.append("court"))

    original_refresh = lambda path=None: 0
    monkeypatch.setattr(corpus_refresh, "refresh_corpus_once", original_refresh)

    safe.install_production_cost_speed_optimizer_safe()

    assert calls == ["scope", "rag", "repair-skip", "court"]
    assert corpus_refresh.refresh_corpus_once is original_refresh


def test_external_only_classifier_never_skips_substantive_or_mixed_defects():
    from korgan.production_cost_speed_optimizer import _all_issues_external_only

    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "не указан адрес ответчика",
        "не указан БИН истца",
    ]) is True

    assert _all_issues_external_only([
        "не указан адрес ответчика",
        "есть правовая ссылка, не прошедшая source-bound/corpus проверку",
    ]) is False

    assert _all_issues_external_only([
        "не определено конкретное наименование суда",
        "требование о неустойке исчезло из ПРОШУ СУД",
    ]) is False
