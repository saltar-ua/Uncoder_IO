from app.translator.core.models.platform_details import PlatformDetails

GRAYLOG_QUERY_DETAILS = {
    "siem_type": "graylog-lucene-query",
    "name": "Graylog",
    "group_name": "Graylog",
    "platform_name": "Query",
    "group_id": "graylog",
}


graylog_details = PlatformDetails(**GRAYLOG_QUERY_DETAILS)
