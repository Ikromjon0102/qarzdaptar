from django import template

register = template.Library()

@register.filter(name='space_format')
def space_format(value):
    """
    Raqamni 1 000 000 ko'rinishida (probel bilan) chiqaradi.
    """
    try:
        # Avval floatga, keyin intga o'tkazib yaxlitlaymiz (xuddi floatformat:0 kabi)
        value = int(float(value))
        # F-string yordamida vergul bilan ajratamiz, keyin vergulni probelga almashtiramiz
        return f'{value:,}'.replace(',', ' ')
    except (ValueError, TypeError):
        return value