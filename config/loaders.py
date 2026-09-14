"""Typed loaders for every YAML file under config/.

Invalid structure fails fast with ConfigError. Deal and action weight maps
must each sum to 1.0 within WEIGHT_SUM_TOLERANCE.

Machine-specific overrides (config/*.local.yaml) are ignored.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

CONFIG_DIR = Path(__file__).parent
WEIGHT_SUM_TOLERANCE = 1e-6
_LOCAL_SUFFIX = ".local.yaml"


class ConfigError(ValueError):
    """Raised when a config file is missing, unreadable, or invalid."""


def _strict() -> ConfigDict:
    return ConfigDict(extra="forbid")


def _assert_weights_sum_to_one(weights: dict[str, float], *, label: str) -> None:
    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_SUM_TOLERANCE:
        raise ValueError(
            f"{label} weights sum to {total:.6f}, expected 1.0 "
            f"(tolerance {WEIGHT_SUM_TOLERANCE})"
        )


# ---------------------------------------------------------------------------
# priority_weights.yaml
# ---------------------------------------------------------------------------


class DealWeights(BaseModel):
    model_config = _strict()
    deal_value: float = Field(ge=0)
    close_urgency: float = Field(ge=0)
    stale_activity: float = Field(ge=0)
    outstanding_commitment: float = Field(ge=0)
    meeting_proximity: float = Field(ge=0)

    @model_validator(mode="after")
    def _sum_to_one(self) -> DealWeights:
        _assert_weights_sum_to_one(self.model_dump(), label="deal")
        return self


class ActionWeights(BaseModel):
    model_config = _strict()
    inherited_deal_score: float = Field(ge=0)
    due_date: float = Field(ge=0)

    @model_validator(mode="after")
    def _sum_to_one(self) -> ActionWeights:
        _assert_weights_sum_to_one(self.model_dump(), label="action")
        return self


class DealValueScale(BaseModel):
    model_config = _strict()
    reference_value_gbp: float = Field(gt=0)
    min_signal_for_known_value: float


class CloseUrgencyScale(BaseModel):
    model_config = _strict()
    points: list[tuple[int, float]]
    unknown_close_date_signal: float


class StaleActivityScale(BaseModel):
    model_config = _strict()
    points: list[tuple[int, float]]
    cap_when_close_beyond_days: int
    cap_signal: float
    unknown_activity_signal: float


class OutstandingCommitmentScale(BaseModel):
    model_config = _strict()
    user_owes_customer_overdue: float
    user_owes_customer_due_within_days: int
    user_owes_customer_due_soon: float
    user_owes_customer_open: float
    customer_owes_user_overdue: float
    none: float


class MeetingProximityScale(BaseModel):
    model_config = _strict()
    today: float
    tomorrow: float
    within_days: int
    within_signal: float
    held_yesterday_no_followup: float
    none: float


class AttentionThresholds(BaseModel):
    model_config = _strict()
    high: float
    medium: float


class UserAdjustments(BaseModel):
    model_config = _strict()
    boost_step_points: int
    max_boost_points: int
    strategic_account_points: int
    pinned_rank_wins: bool


class DealPriority(BaseModel):
    model_config = _strict()
    weights: DealWeights
    deal_value: DealValueScale
    close_urgency: CloseUrgencyScale
    stale_activity: StaleActivityScale
    outstanding_commitment: OutstandingCommitmentScale
    meeting_proximity: MeetingProximityScale
    attention_thresholds: AttentionThresholds
    user_adjustments: UserAdjustments


class ActionDueDateScale(BaseModel):
    model_config = _strict()
    overdue_base: float
    overdue_per_day: float
    today: float
    tomorrow: float
    within_days: int
    within_signal: float
    no_due_date: float


class ActionPriority(BaseModel):
    model_config = _strict()
    weights: ActionWeights
    due_date: ActionDueDateScale
    tier_by_type: dict[str, Literal[1, 2, 3]]
    no_deal_inherited_score: float


class Explanations(BaseModel):
    model_config = _strict()
    min_contribution_for_bullet: float
    max_bullets: int = Field(ge=1)


class PriorityWeightsConfig(BaseModel):
    model_config = _strict()
    version: int
    deal: DealPriority
    action: ActionPriority
    explanations: Explanations


# ---------------------------------------------------------------------------
# ai.yaml
# ---------------------------------------------------------------------------


class AiTaskPolicy(BaseModel):
    model_config = _strict()
    enabled: bool
    max_input_chars: int | None = None
    require_quotes: bool | None = None
    quote_match_min_ratio: float | None = Field(default=None, ge=0, le=1)
    drop_items_without_verified_quote: bool | None = None
    max_items: int | None = None
    max_output_sentences: int | None = None
    require_citation_per_sentence: bool | None = None


class AiFallback(BaseModel):
    model_config = _strict()
    rules_extractor: bool
    rules_confidence_cap: float = Field(ge=0, le=1)
    templated_summaries: bool


class AiPrivacy(BaseModel):
    model_config = _strict()
    log_every_call: bool
    redact_email_addresses: bool
    never_send: list[str]
    show_transmission_banner: bool


class OpenAiProvider(BaseModel):
    model_config = _strict()
    model: str
    temperature: float
    response_format: str
    timeout_seconds: int = Field(gt=0)


class LocalProvider(BaseModel):
    model_config = _strict()
    base_url_env: str
    model: str
    temperature: float
    timeout_seconds: int = Field(gt=0)


class AiProviders(BaseModel):
    model_config = _strict()
    openai: OpenAiProvider
    local: LocalProvider


class AiConfig(BaseModel):
    model_config = _strict()
    version: int
    tasks: dict[str, AiTaskPolicy]
    fallback: AiFallback
    privacy: AiPrivacy
    providers: AiProviders


# ---------------------------------------------------------------------------
# excel_mapping.yaml
# ---------------------------------------------------------------------------


class ExcelFile(BaseModel):
    model_config = _strict()
    synced_path: str | None = None
    drop_folder: str
    glob: str
    copy_before_open: bool = True


class ExcelSheet(BaseModel):
    model_config = _strict()
    name: str
    is_closed: bool
    header_row: int = Field(ge=1)
    won_column: str | None = None
    won_values: list[str] | None = None


class ExcelColumns(BaseModel):
    model_config = _strict()
    name: str
    company_name: str
    deal_value: str
    currency: str | None = None
    stage: str | None = None
    close_date: str | None = None
    owner: str | None = None
    last_activity_at: str | None = None
    notes: str | None = None


class ExcelParsing(BaseModel):
    model_config = _strict()
    date_formats: list[str]
    value_strip_chars: str
    skip_rows_where_empty: list[str]


class ExcelMappingConfig(BaseModel):
    model_config = _strict()
    version: int
    file: ExcelFile
    product: str
    default_currency: str
    sheets: list[ExcelSheet]
    columns: ExcelColumns
    stable_key_columns: list[str]
    parsing: ExcelParsing


# ---------------------------------------------------------------------------
# matching.yaml
# ---------------------------------------------------------------------------


class MatchThresholds(BaseModel):
    model_config = _strict()
    auto_link: float = Field(ge=0, le=1)
    provisional_link: float = Field(ge=0, le=1)


class RuleConfidence(BaseModel):
    model_config = _strict()
    external_id: float = Field(ge=0, le=1)
    user_confirmed_alias: float = Field(ge=0, le=1)
    email_domain: float = Field(ge=0, le=1)
    contact_email: float = Field(ge=0, le=1)
    calendar_correlation: float = Field(ge=0, le=1)
    company_name_exact: float = Field(ge=0, le=1)
    company_name_fuzzy_high: float = Field(ge=0, le=1)
    company_name_fuzzy_mid: float = Field(ge=0, le=1)
    contact_full_name: float = Field(ge=0, le=1)
    memory_reference: float = Field(ge=0, le=1)


class CompanyNameNormalisation(BaseModel):
    model_config = _strict()
    lowercase: bool
    strip_suffixes: list[str]
    strip_punctuation: bool
    collapse_whitespace: bool


class DealDisambiguation(BaseModel):
    model_config = _strict()
    prefer_open: bool
    product_hints: dict[str, list[str]]
    prefer_most_recent_activity: bool
    ask_if_top_two_within: float = Field(ge=0, le=1)


class MatchingConfig(BaseModel):
    model_config = _strict()
    version: int
    thresholds: MatchThresholds
    rule_confidence: RuleConfidence
    company_name_normalisation: CompanyNameNormalisation
    freemail_domains: list[str]
    deal_disambiguation: DealDisambiguation


# ---------------------------------------------------------------------------
# sources.yaml
# ---------------------------------------------------------------------------


class ProductEntry(BaseModel):
    model_config = _strict()
    label: str
    source_of_truth: str


class CurrencyConfig(BaseModel):
    model_config = _strict()
    base: str
    rates_to_gbp: dict[str, float]


class ConnectorFallback(BaseModel):
    model_config = _strict()
    mode: Literal["api", "file", "disabled"]
    drop_folder: str
    glob: str


class ConnectorEntry(BaseModel):
    model_config = _strict()
    tier: int = Field(ge=1)
    label: str
    mode: Literal["api", "file", "disabled"]
    enabled: bool
    required_env: list[str] | None = None
    writes: dict[str, bool] | None = None
    sync: dict[str, Any] | None = None
    fallback: ConnectorFallback | None = None
    mapping: str | None = None
    drop_folder: str | None = None
    extensions: list[str] | None = None
    user_email_addresses: list[str] | None = None
    user_speaker_names: list[str] | None = None
    match_to_meeting_window_minutes: int | None = None
    row_key_columns: list[str] | None = None


class RefreshConfig(BaseModel):
    model_config = _strict()
    morning_refresh_hour_local: int = Field(ge=0, le=23)
    connector_timeout_seconds: int = Field(gt=0)
    continue_on_connector_failure: bool


class SourcesConfig(BaseModel):
    model_config = _strict()
    version: int
    products: dict[str, ProductEntry]
    currency: CurrencyConfig
    connectors: dict[str, ConnectorEntry]
    refresh: RefreshConfig


class AppConfig(BaseModel):
    """All committed YAML configs, keyed to filenames without suffix."""

    model_config = _strict()
    ai: AiConfig
    excel_mapping: ExcelMappingConfig
    matching: MatchingConfig
    priority_weights: PriorityWeightsConfig
    sources: SourcesConfig


MODELS: dict[str, type[BaseModel]] = {
    "ai": AiConfig,
    "excel_mapping": ExcelMappingConfig,
    "matching": MatchingConfig,
    "priority_weights": PriorityWeightsConfig,
    "sources": SourcesConfig,
}


def config_yaml_files(config_dir: Path | None = None) -> list[Path]:
    directory = config_dir or CONFIG_DIR
    return sorted(
        p for p in directory.glob("*.yaml") if not p.name.endswith(_LOCAL_SUFFIX)
    )


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(f"Config file not found: {path}")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path} must contain a mapping at the top level")
    return raw


def _parse(model: type[BaseModel], path: Path) -> BaseModel:
    data = _load_yaml(path)
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        raise ConfigError(f"Invalid config {path}:\n{exc}") from exc


def load_ai(path: Path | None = None) -> AiConfig:
    return _parse(AiConfig, path or CONFIG_DIR / "ai.yaml")  # type: ignore[return-value]


def load_excel_mapping(path: Path | None = None) -> ExcelMappingConfig:
    return _parse(ExcelMappingConfig, path or CONFIG_DIR / "excel_mapping.yaml")  # type: ignore[return-value]


def load_matching(path: Path | None = None) -> MatchingConfig:
    return _parse(MatchingConfig, path or CONFIG_DIR / "matching.yaml")  # type: ignore[return-value]


def load_priority_weights(path: Path | None = None) -> PriorityWeightsConfig:
    return _parse(PriorityWeightsConfig, path or CONFIG_DIR / "priority_weights.yaml")  # type: ignore[return-value]


def load_sources(path: Path | None = None) -> SourcesConfig:
    return _parse(SourcesConfig, path or CONFIG_DIR / "sources.yaml")  # type: ignore[return-value]


_LOADERS = {
    "ai": load_ai,
    "excel_mapping": load_excel_mapping,
    "matching": load_matching,
    "priority_weights": load_priority_weights,
    "sources": load_sources,
}


def load_all(config_dir: Path | None = None) -> AppConfig:
    """Load and validate every committed YAML file in config/.

    Unknown stems (other than *.local.yaml) and missing expected files fail fast.
    """
    directory = config_dir or CONFIG_DIR
    files = {p.stem: p for p in config_yaml_files(directory)}
    expected = set(_LOADERS)
    extra = sorted(set(files) - expected)
    missing = sorted(expected - set(files))
    if extra:
        raise ConfigError(
            "No typed loader for config file(s): " + ", ".join(extra)
        )
    if missing:
        raise ConfigError(
            "Missing expected config file(s): "
            + ", ".join(f"{name}.yaml" for name in missing)
        )
    loaded = {stem: _LOADERS[stem](files[stem]) for stem in sorted(expected)}
    return AppConfig.model_validate(loaded)
