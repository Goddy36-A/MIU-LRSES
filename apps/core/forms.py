from django import forms


class BootstrapFormMixin:
    """Adds Bootstrap classes and HTML5 date/datetime widgets to every field."""

    DATETIME_FORMATS = ["%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field, forms.DateTimeField):
                field.widget = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
                field.input_formats = self.DATETIME_FORMATS
            elif isinstance(field, forms.DateField):
                field.widget = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select):  # includes SelectMultiple
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = css
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("rows", 3)
