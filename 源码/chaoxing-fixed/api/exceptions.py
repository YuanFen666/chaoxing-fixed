try:
    from requests.exceptions import JSONDecodeError
except ImportError:
    from json import JSONDecodeError


class LoginError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class InputFormatError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class MaxRollBackExceeded(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class MaxRetryExceeded(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class FontDecodeError(Exception):
    def __init__(self, *args: object):
        super().__init__(*args)


class StudyAborted(BaseException):
    """
    用户主动停止（继承 BaseException，不被业务代码的 except Exception 吞掉）。

    注意：worker 线程、watchdog、JobProcessor.run 都认这个异常做收操流程，
    抛出前请确认想要的是「中止整个运行」，普通失败请用别的异常。
    """

    def __init__(self, *args: object):
        super().__init__(*args)
