"""User-profile domain enums. Documents live in the ``user_profiles`` collection."""
import enum


class Gender(str, enum.Enum):
    man        = "man"
    woman      = "woman"
    non_binary = "non_binary"
    other      = "other"


class RelationshipGoal(str, enum.Enum):
    serious   = "serious"
    casual    = "casual"
    open      = "open"
    undecided = "undecided"


class RelationshipStagePref(str, enum.Enum):
    first_date   = "first_date"
    second_third = "second_third"
    together     = "together"


class SocialEnergy(str, enum.Enum):
    introvert = "introvert"
    ambivert  = "ambivert"
    extrovert = "extrovert"


class CommunicationStyle(str, enum.Enum):
    deep_talker  = "deep_talker"
    light_banter = "light_banter"
    mix          = "mix"


class PreferredTime(str, enum.Enum):
    weekday_evenings    = "weekday_evenings"
    weekend_afternoons  = "weekend_afternoons"
    weekend_evenings    = "weekend_evenings"


class AlcoholPreference(str, enum.Enum):
    yes       = "yes"
    no        = "no"
    sometimes = "sometimes"
