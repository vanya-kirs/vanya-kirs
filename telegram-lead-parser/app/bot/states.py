from aiogram.fsm.state import State, StatesGroup


class MainMenuStates(StatesGroup):
    main = State()


class SourceStates(StatesGroup):
    waiting_url = State()
    waiting_name = State()
    waiting_import = State()


class CriteriaStates(StatesGroup):
    waiting_name = State()
    waiting_description = State()
    waiting_min_score = State()
    confirming_activate = State()


class LeadsStates(StatesGroup):
    browsing = State()
    filtering = State()


class JoinQueueStates(StatesGroup):
    waiting_priority = State()
