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
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Optional, Union

from app.translator.core.custom_types.tokens import GroupType, OperatorType
from app.translator.core.custom_types.values import ValueType
from app.translator.core.escape_manager import EscapeManager
from app.translator.core.exceptions.parser import (
    QueryParenthesesException,
    TokenizerGeneralException,
    UnsupportedOperatorException,
)
from app.translator.core.mapping import SourceMapping
from app.translator.core.models.field import Field, FieldValue, Keyword
from app.translator.core.models.functions.base import Function
from app.translator.core.models.functions.sort import SortArg
from app.translator.core.models.identifier import Identifier
from app.translator.tools.utils import get_match_group

TOKEN_TYPE = Union[FieldValue, Keyword, Identifier]


class BaseTokenizer(ABC):
    @abstractmethod
    def tokenize(self, query: str) -> list[Union[FieldValue, Keyword, Identifier]]:
        raise NotImplementedError


class QueryTokenizer(BaseTokenizer):
    # used to generate re pattern. so the keys order is important
    single_value_operators_map: ClassVar[dict[str, str]] = {}
    # used to generate re pattern. so the keys order is important
    multi_value_operators_map: ClassVar[dict[str, str]] = {}
    operators_map: ClassVar[dict[str, str]] = {}  # used to generate re pattern. so the keys order is important

    logical_operator_pattern = r"\s?(?P<logical_operator>and|or|not|AND|OR|NOT)\s?"
    field_value_pattern = r"""^___field___\s*___operator___\s*___value___"""
    base_value_pattern = r"(?:___value_pattern___)"

    # do not modify, use subclasses to define this attribute
    field_pattern: str = None
    _value_pattern: str = None
    value_pattern: str = None
    multi_value_pattern: str = None
    keyword_pattern: str = None

    multi_value_delimiter = ","
    wildcard_symbol = None
    escape_manager: EscapeManager = None

    def __init_subclass__(cls, **kwargs):
        cls._validate_re_patterns()
        cls.value_pattern = cls.base_value_pattern.replace("___value_pattern___", cls._value_pattern)
        cls.operators_map = {**cls.single_value_operators_map, **cls.multi_value_operators_map}
        cls.operator_pattern = rf"""(?:___field___\s*(?P<operator>(?:{'|'.join(cls.operators_map)})))\s*"""

    @classmethod
    def _validate_re_patterns(cls) -> None:
        if not all([cls.field_pattern, cls._value_pattern]):
            raise ValueError(f"{cls.__name__} re patterns must be set")

    def map_operator(self, operator: str) -> str:
        try:
            return self.operators_map[operator.lower()]
        except KeyError as e:
            raise UnsupportedOperatorException(operator) from e

    def search_field(self, query: str) -> str:
        field_search = re.search(self.field_pattern, query)
        if field_search is None:
            raise TokenizerGeneralException(error=f"Field couldn't be found in query part: {query}")
        return field_search.group("field_name")

    def escape_field_name(self, field_name: str) -> str:
        return field_name.replace(".", r"\.")

    def search_operator(self, query: str, field_name: str) -> str:
        field_name = self.escape_field_name(field_name)
        operator_pattern = self.operator_pattern.replace("___field___", field_name)
        compiled_operator_regex = re.compile(operator_pattern, re.IGNORECASE)
        if (operator_search := re.search(compiled_operator_regex, query)) is None:
            raise TokenizerGeneralException(error=f"Operator couldn't be found in query part: {query}")

        operator = operator_search.group("operator")
        return operator.strip(" ")

    def get_operator_and_value(self, match: re.Match, operator: str = OperatorType.EQ) -> tuple[str, Any]:
        return operator, get_match_group(match, group_name=ValueType.value)

    @staticmethod
    def clean_multi_value(value: Union[int, str]) -> Union[int, str]:
        if isinstance(value, str):
            value = value.strip(" ")
            if value.startswith("'") and value.endswith("'") or value.startswith('"') and value.endswith('"'):
                value = value[1:-1]

        return value

    def search_value(self, query: str, operator: str, field_name: str) -> tuple[str, str, Any]:
        field_value_pattern = self.get_field_value_pattern(operator, field_name)
        value_pattern = self.value_pattern
        is_multi = False
        if operator.lower() in self.multi_value_operators_map:
            value_pattern = self.multi_value_pattern
            is_multi = True

        field_value_pattern = field_value_pattern.replace("___value___", value_pattern)
        field_value_regex = re.compile(field_value_pattern, re.IGNORECASE)
        field_value_search = re.match(field_value_regex, query)
        if field_value_search is None:
            raise TokenizerGeneralException(error=f"Value couldn't be found in query part: {query}")

        operator, value = self.get_operator_and_value(field_value_search, self.map_operator(operator))
        value = [self.clean_multi_value(v) for v in value.split(",")] if is_multi else value
        pos = field_value_search.end()
        return query[pos:], operator, value

    def search_keyword(self, query: str) -> tuple[Keyword, str]:
        keyword_search = re.search(self.keyword_pattern, query)
        _, value = self.get_operator_and_value(keyword_search)
        keyword = Keyword(value=value)
        pos = keyword_search.end()
        return keyword, query[pos:]

    def get_field_value_pattern(self, operator: str, field_name: str) -> str:
        field_value_pattern = self.field_value_pattern.replace("___field___", self.escape_field_name(field_name))
        return field_value_pattern.replace("___operator___", operator)

    @staticmethod
    def _clean_value(value: str, wildcard_symbol: str) -> str:
        return value.strip(wildcard_symbol) if wildcard_symbol else value

    @staticmethod
    def __get_operator_token(value: str, operator: str, wildcard_symbol: str) -> Identifier:
        if not wildcard_symbol:
            return Identifier(token_type=operator)

        if operator == OperatorType.REGEX and not (
            value.startswith(wildcard_symbol) and value.endswith(wildcard_symbol)
        ):
            return Identifier(token_type=OperatorType.REGEX)

        if value.startswith(wildcard_symbol) and value.endswith(wildcard_symbol):
            return Identifier(token_type=OperatorType.CONTAINS)
        if value.startswith(wildcard_symbol):
            return Identifier(token_type=OperatorType.ENDSWITH)
        if value.endswith(wildcard_symbol):
            return Identifier(token_type=OperatorType.STARTSWITH)
        return Identifier(token_type=operator)

    def process_value_wildcard_symbols(
        self, value: Union[list[str], str], operator: str, wildcard_symbol: Optional[str]
    ) -> tuple[Union[list[str], str], Identifier]:
        if isinstance(value, list):
            op = self.__get_operator_token(value=value[0], operator=operator, wildcard_symbol=wildcard_symbol)
            return [self._clean_value(value=v, wildcard_symbol=wildcard_symbol) for v in value], op

        op = self.__get_operator_token(value=value, operator=operator, wildcard_symbol=wildcard_symbol)
        return self._clean_value(value, wildcard_symbol), op

    @staticmethod
    def create_field_value(field_name: str, operator: Identifier, value: Union[str, list]) -> FieldValue:
        return FieldValue(source_name=field_name, operator=operator, value=value)

    def search_field_value(self, query: str) -> tuple[FieldValue, str]:
        field_name = self.search_field(query)
        operator = self.search_operator(query, field_name)
        query, operator, value = self.search_value(query=query, operator=operator, field_name=field_name)
        value, operator_token = self.process_value_wildcard_symbols(
            value=value, operator=operator, wildcard_symbol=self.wildcard_symbol
        )
        field_value = self.create_field_value(field_name=field_name, operator=operator_token, value=value)
        return field_value, query

    def _match_field_value(self, query: str, white_space_pattern: str = r"\s+") -> bool:
        single_value_operator_group = rf"(?:{'|'.join(self.single_value_operators_map)})"
        single_value_pattern = rf"""{self.field_pattern}\s*{single_value_operator_group}\s*{self.value_pattern}\s*"""
        if re.match(single_value_pattern, query, re.IGNORECASE):
            return True

        if self.multi_value_operators_map:
            multi_value_operator_group = rf"(?:{'|'.join(self.multi_value_operators_map)})"
            pattern = f"{self.field_pattern}{white_space_pattern}{multi_value_operator_group}{white_space_pattern}"
            multi_value_pattern = rf"{pattern}{self.multi_value_pattern}"
            if re.match(multi_value_pattern, query, re.IGNORECASE):
                return True

        return False

    def _get_identifier(self, query: str) -> tuple[Union[FieldValue, Keyword, Identifier], str]:
        query = query.strip("\n").strip(" ").strip("\n")
        if query.startswith(GroupType.L_PAREN):
            return Identifier(token_type=GroupType.L_PAREN), query[1:]
        if query.startswith(GroupType.R_PAREN):
            return Identifier(token_type=GroupType.R_PAREN), query[1:]
        if logical_operator_search := re.match(self.logical_operator_pattern, query):
            logical_operator = logical_operator_search.group("logical_operator")
            pos = logical_operator_search.end()
            return Identifier(token_type=logical_operator.lower()), query[pos:]
        if self._match_field_value(query):
            return self.search_field_value(query)
        if self.keyword_pattern and re.match(self.keyword_pattern, query):
            return self.search_keyword(query)

        raise TokenizerGeneralException("Unsupported query entry")

    @staticmethod
    def _validate_parentheses(tokens: list[TOKEN_TYPE]) -> None:
        parentheses = []
        for token in tokens:
            if isinstance(token, Identifier) and token.token_type in (GroupType.L_PAREN, GroupType.R_PAREN):
                if token.token_type == GroupType.L_PAREN:
                    parentheses.append(token)
                elif not parentheses or parentheses[-1].token_type == GroupType.R_PAREN:
                    raise QueryParenthesesException
                else:
                    parentheses.pop()
        if parentheses:
            raise QueryParenthesesException

    def tokenize(self, query: str) -> list[Union[FieldValue, Keyword, Identifier]]:
        tokenized = []
        while query:
            identifier, query = self._get_identifier(query=query)
            tokenized.append(identifier)
        self._validate_parentheses(tokenized)
        return tokenized

    @staticmethod
    def filter_tokens(
        tokens: list[TOKEN_TYPE], token_type: Union[type[FieldValue], type[Keyword], type[Identifier]]
    ) -> list[TOKEN_TYPE]:
        return [token for token in tokens if isinstance(token, token_type)]

    def get_field_tokens_from_func_args(
        self, args: list[Union[Field, FieldValue, Keyword, Identifier, Function, SortArg]]
    ) -> list[Field]:
        result = []
        for arg in args:
            if isinstance(arg, Field):
                result.append(arg)
            elif isinstance(arg, FieldValue):
                result.append(arg.field)
            elif isinstance(arg, Function):
                result.extend(self.get_field_tokens_from_func_args(args=arg.args))
                result.extend(self.get_field_tokens_from_func_args(args=arg.by_clauses))
            elif isinstance(arg, SortArg):
                result.append(arg.field)
        return result

    @staticmethod
    def set_field_tokens_generic_names_map(
        tokens: list[Field], source_mappings: list[SourceMapping], default_mapping: SourceMapping
    ) -> None:
        for token in tokens:
            token.set_generic_names_map(source_mappings, default_mapping)
