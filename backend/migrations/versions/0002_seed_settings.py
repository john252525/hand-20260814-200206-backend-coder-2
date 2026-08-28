import json
from alembic import op
import sqlalchemy as sa

revision = '0002_seed_settings'
down_revision = '0001_initial'
branch_labels = None
depends_on = None

DEFAULT_SETTINGS = {
    'company': {
        'legal_name': '', 'inn': '', 'kpp': '', 'ogrn': '', 'legal_address': '',
        'contact_person': '', 'contact_email': '', 'contact_phone': '', 'email_signature': ''
    },
    'scoring': {
        'min_total_score': 60, 'min_margin_percent': 15.0, 'max_risk_level': 'MEDIUM',
        'weight_margin': 40, 'weight_simplicity': 30, 'weight_volume': 20, 'weight_competition': 10,
        'volume_thresholds': {'low': 100000, 'medium': 1000000, 'high': 5000000},
        'volume_scores': {'low': 20, 'medium': 50, 'high': 80, 'very_high': 95},
        'default_competition_score': 50, 'margin_calculation_mode': 'auto', 'margin_fallback_score': 50
    },
    'communication': {
        'max_suppliers_per_lot': 10, 'response_timeout_hours': 48, 'reminder_after_hours': 24,
        'max_clarification_cycles': 2, 'max_discount_requests_per_supplier': 2,
        'price_diff_threshold_percent': 5.0,
        'channel_priority': ['email', 'telegram', 'whatsapp', 'web_form'],
        'email_config': {'smtp_host': '', 'smtp_port': 587, 'smtp_user': '', 'smtp_password_encrypted': '',
                         'smtp_use_tls': True, 'imap_host': '', 'imap_port': 993, 'imap_user': '',
                         'imap_password_encrypted': '', 'imap_use_ssl': True},
        'telegram_bot_token': '', 'whatsapp_api_token': ''
    },
    'tender_source': {
        'api_url': '', 'api_key_encrypted': '', 'poll_interval_minutes': 30, 'is_active': True,
        'config': {'rate_limit_rps': 5, 'timeout_seconds': 30, 'retry_count': 3, 'page_size': 100}
    },
    'ml': {
        'min_samples_for_training': 100, 'retrain_interval_days': 30,
        'features_list': ['nmck', 'positions_count', 'category_id', 'deadline_days',
                          'has_license_requirement', 'has_sro_requirement', 'security_bid_ratio'],
        'model_type': 'gradient_boosting', 'last_trained_at': None, 'model_metrics': {}
    },
    'templates': {
        'cp_request': {
            'subject': 'Запрос коммерческого предложения: {lot_name}',
            'body': 'Добрый день!\n\nПрошу предоставить коммерческое предложение на поставку следующего оборудования:\n\n{positions_table}\n\nСрок поставки: до {deadline_date}\nОбъём: {total_quantity} единиц\n\nПрошу указать:\n- Цену за единицу\n- Сроки поставки\n- Условия оплаты\n- Наличие товара на складе\n\n{company_signature}'
        },
        'cp_reminder': {
            'subject': 'Напоминание: запрос КП {lot_name}',
            'body': 'Добрый день!\n\nНапоминаю о ранее направленном запросе коммерческого предложения. Будем признательны за оперативный ответ.\n\n{company_signature}'
        },
        'clarification': {
            'subject': 'Уточнение по КП: {lot_name}',
            'body': 'Добрый день!\n\nБлагодарим за предоставленное КП. Просим уточнить следующую информацию:\n\n{clarification_items}\n\n{company_signature}'
        },
        'discount_request': {
            'subject': 'Запрос улучшения условий: {lot_name}',
            'body': 'Добрый день!\n\nБлагодарим за предоставленное КП. В настоящий момент мы рассматриваем несколько предложений. Конкуренты предлагают более выгодные условия по позициям:\n\n{discount_positions}\n\nБудем признательны, если вы сможете пересмотреть цены.\n\n{company_signature}'
        }
    },
    'filters': {
        'min_similarity_accept': 0.75, 'min_similarity_uncertain': 0.60,
        'max_tender_age_days': 30, 'skip_archived_customers': True
    }
}


def upgrade():
    conn = op.get_bind()
    for section, values in DEFAULT_SETTINGS.items():
        for key, value in values.items():
            conn.execute(
                sa.text("INSERT INTO settings (section, key, value, description) VALUES (:section, :key, :value, '')"),
                {'section': section, 'key': key, 'value': json.dumps(value)}
            )


def downgrade():
    op.execute("DELETE FROM settings")
