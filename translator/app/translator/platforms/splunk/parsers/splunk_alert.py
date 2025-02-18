"""
Uncoder IO Commercial Edition License
-----------------------------------------------------------------
Copyright (c) 2023 SOC Prime, Inc.

This file is part of the Uncoder IO Commercial Edition ("CE") and is
licensed under the Uncoder IO Non-Commercial License (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    https://github.com/UncoderIO/UncoderIO/blob/main/LICENSE

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-----------------------------------------------------------------
"""

import re
from typing import Optional

from app.translator.core.models.parser_output import MetaInfoContainer, SiemContainer
from app.translator.core.models.platform_details import PlatformDetails
from app.translator.platforms.splunk.const import splunk_alert_details
from app.translator.platforms.splunk.parsers.splunk import SplunkParser


class SplunkAlertParser(SplunkParser):
    details: PlatformDetails = splunk_alert_details

    @staticmethod
    def _get_meta_info(source_mapping_ids: list[str], meta_info: Optional[str]) -> MetaInfoContainer:
        description = re.search(r"description\s*=\s*(?P<query>.+)", meta_info).group()
        description = description.replace("description = ", "")
        return MetaInfoContainer(source_mapping_ids=source_mapping_ids, description=description)

    def parse(self, text: str) -> SiemContainer:
        query = re.search(r"search\s*=\s*(?P<query>.+)", text).group("query")
        log_sources, functions, query = self._parse_query(query)
        tokens, source_mappings = self.get_tokens_and_source_mappings(query, log_sources)

        return SiemContainer(
            query=tokens,
            meta_info=self._get_meta_info([source_mapping.source_id for source_mapping in source_mappings], text),
            functions=functions,
        )
