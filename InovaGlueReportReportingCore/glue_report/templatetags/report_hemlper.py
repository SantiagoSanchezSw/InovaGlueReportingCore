from django import template
from typing import List, Any
import re

register = template.Library()


@register.simple_tag()
def generic_filter(values_list: List[Any], filter_query: str):
    if filter_query:
        return list(
            filter(lambda i: eval(filter_query), values_list)
        )
    return values_list


@register.simple_tag()
def text_map_numeric_list(value: str):
    coincidences = re.findall('(\d+\.)', value)
    if len(coincidences) > 0:
        coincidences = coincidences[1:]
    for match in coincidences:
        value = value.replace(
            match,
            '\n {}'.format(match),
        )
    return value

