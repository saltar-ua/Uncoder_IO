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


from app.translator.core.mixins.rule import JsonRuleMixin
from app.translator.core.models.parser_output import MetaInfoContainer, SiemContainer
from app.translator.core.models.platform_details import PlatformDetails
from app.translator.platforms.microsoft.const import microsoft_sentinel_rule_details
from app.translator.platforms.microsoft.parsers.microsoft_sentinel import MicrosoftParser


class MicrosoftRuleParser(MicrosoftParser, JsonRuleMixin):
    details: PlatformDetails = microsoft_sentinel_rule_details

    @staticmethod
    def _get_meta_info(source_mapping_ids: list[str], meta_info: dict) -> MetaInfoContainer:
        return MetaInfoContainer(
            source_mapping_ids=source_mapping_ids,
            title=meta_info.get("displayName"),
            description=meta_info.get("description"),
        )

    def parse(self, text: str) -> SiemContainer:
        rule = self.load_rule(text=text)
        query, log_sources, functions = self._parse_query(query=rule.get("query"))
        tokens, source_mappings = self.get_tokens_and_source_mappings(query, log_sources)

        return SiemContainer(
            query=tokens,
            meta_info=self._get_meta_info(
                source_mapping_ids=[source_mapping.source_id for source_mapping in source_mappings], meta_info=rule
            ),
            functions=functions,
        )
