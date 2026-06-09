from django import template

register = template.Library()

_WIDGET_CLASS = {
    "TextInput": "govuk-input",
    "EmailInput": "govuk-input",
    "NumberInput": "govuk-input",
    "PasswordInput": "govuk-input",
    "URLInput": "govuk-input",
    "Textarea": "govuk-textarea",
    "Select": "govuk-select",
    "CheckboxInput": "govuk-checkboxes__input",
}


@register.filter
def as_govuk(field):
    """Render a bound field's widget with the appropriate GOV.UK class."""
    widget_name = type(field.field.widget).__name__
    base_class = _WIDGET_CLASS.get(widget_name)
    if not base_class:
        return field
    css = f"{base_class} {base_class}--error" if field.errors else base_class
    return field.as_widget(attrs={"class": css})


@register.filter
def has_tag(tags, tag):
    """Check whether a tag appears in allauth's comma-separated tag string or tag set."""
    if isinstance(tags, str):
        return tag in tags.split(",")
    return tag in (tags or set())
