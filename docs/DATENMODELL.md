# HausCheckHAOS – Datenmodell

Version: 0.1  
Status: Entwurf

## Grundprinzip

HausCheck speichert dauerhafte Hausakten. Ein Haus kann auf mehreren Portalen erscheinen und sich über die Zeit verändern. Deshalb wird zwischen Hausakte, Inseratquelle, Medien, Lageprüfung und Bewertung getrennt.

## SearchProfile

Persönliches Suchprofil mit Region, Budget, Mindestwohnfläche, bevorzugter Grundstücksgröße, Ausschlusskriterien, Portal-Auswahl und Suchzeitplan.

Wichtige Felder:

- `id`
- `name`
- `enabled`
- `locations`
- `max_price_eur`
- `soft_max_price_eur`
- `min_living_area_m2`
- `preferred_min_plot_area_m2`
- `preferred_year_from`
- `max_expected_investment_eur`
- `exclude_major_roads`
- `preferred_energy_classes`
- `oil_heating_policy`
- `schedule`

## SearchRun

Protokoll eines Suchlaufs.

Wichtige Felder:

- `id`
- `profile_id`
- `started_at`
- `finished_at`
- `status`
- `used_search_urls`
- `found_count`
- `candidate_count`
- `new_count`
- `updated_count`
- `rejected_count`
- `errors`

## HouseRecord

Dauerhafte Hausakte.

Wichtige Felder:

- `id`
- `created_at`
- `updated_at`
- `status`
- `title`
- `primary_location_text`
- `address_status`
- `location_confidence`
- `favorite`
- `decision_status`
- `decision_reason`
- `notes`

Statuswerte:

- `new`
- `watching`
- `favorite`
- `ask_address`
- `ask_documents`
- `inspect`
- `rejected`
- `archived`

## ListingSource

Ein konkretes Portal-Inserat.

Wichtige Felder:

- `id`
- `house_id`
- `source_name`
- `source_url`
- `canonical_url`
- `external_id`
- `title`
- `description`
- `first_seen_at`
- `last_seen_at`
- `is_online`
- `seller_type`
- `raw_html_path`
- `parser_status`
- `parser_warnings`

## PropertyFacts

Normalisierte Fakten zum Objekt.

Wichtige Felder:

- `house_id`
- `price_eur`
- `living_area_m2`
- `plot_area_m2`
- `rooms`
- `year_built`
- `renovation_year`
- `heating`
- `energy_hwb`
- `energy_fgee`
- `energy_class_hwb`
- `energy_class_fgee`
- `basement`
- `garage`
- `carport`
- `pool`

Regeln:

- Fehlende Werte bleiben leer.
- Grundstück darf niemals aus Wohnfläche abgeleitet werden.
- Wohnfläche und Grundstück müssen aus getrennten Feldquellen stammen.
- HWB und fGEE werden numerisch gespeichert, sofern vorhanden.

## FieldEvidence

Nachweis, woher ein Wert stammt.

Wichtige Felder:

- `house_id`
- `source_id`
- `field_name`
- `value_text`
- `source_label`
- `source_text_snippet`
- `confidence`

Confidence-Werte:

- `verified`
- `derived`
- `estimated`
- `unknown`

## MediaAsset

Lokale Medien.

Wichtige Felder:

- `id`
- `house_id`
- `source_id`
- `kind`
- `original_url`
- `local_path`
- `thumbnail_path`
- `content_hash`
- `mime_type`
- `width`
- `height`
- `file_size_bytes`
- `download_status`
- `created_at`

Medientypen:

- `image`
- `pdf`
- `video`
- `video_frame`
- `screenshot`
- `html`

## LocationAssessment

Lageprüfung.

Wichtige Felder:

- `house_id`
- `address_text`
- `address_status`
- `latitude`
- `longitude`
- `geocode_confidence`
- `distance_major_road_m`
- `distance_b76_m`
- `distance_b69_m`
- `distance_rail_m`
- `distance_sport_m`
- `distance_commercial_m`
- `flood_risk`
- `surface_water_risk`
- `slope_risk`
- `location_summary`
- `limitations`

## ScoreResult

Mehrdimensionale Bewertung.

Wichtige Felder:

- `house_id`
- `overall_score`
- `opportunity_score`
- `living_quality_score`
- `price_value_score`
- `location_score`
- `energy_score`
- `renovation_risk_score`
- `family_score`
- `negotiation_score`
- `confidence`
- `summary`

## FairValueResult

Wert- und Kaufpreisempfehlung.

Wichtige Felder:

- `house_id`
- `fair_value_eur`
- `estimated_investment_eur`
- `recommended_target_price_eur`
- `opening_offer_eur`
- `pain_limit_eur`
- `do_not_pay_above_eur`
- `confidence`
- `confidence_reasons`

## DecisionLog

Entscheidungshistorie.

Beispiele:

- Adresse angefragt
- Unterlagen angefragt
- Favorit gesetzt
- Besichtigung geplant
- Objekt abgelehnt
- Preisänderung erkannt

## Dateistruktur

```text
/share/hauscheck/
├── hauscheck.db
├── projects/
│   └── <house_id>/
│       ├── html/
│       ├── images/
│       ├── pdfs/
│       ├── videos/
│       ├── screenshots/
│       ├── exports/
│       └── analysis/
└── logs/
```
