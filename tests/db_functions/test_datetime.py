from datetime import datetime

import pytz

from django.conf import settings
from django.db import connection
from django.db.models import DateField, DateTimeField, IntegerField, TimeField
from django.db.models.functions import (
    Extract, ExtractDay, ExtractHour, ExtractMinute, ExtractMonth,
    ExtractQuarter, ExtractSecond, ExtractWeek, ExtractWeekDay, ExtractYear,
    Trunc, TruncDate, TruncDay, TruncHour, TruncMinute, TruncMonth,
    TruncQuarter, TruncSecond, TruncTime, TruncYear,
)
from django.test import (
    TestCase, override_settings, skipIfDBFeature, skipUnlessDBFeature,
)
from django.utils import timezone

from .models import DTModel


def microsecond_support(value):
    return value if connection.features.supports_microsecond_precision else value.replace(microsecond=0)


def truncate_to(value, kind, tzinfo=None):
    # Convert to target timezone before truncation
    if tzinfo is not None:
        value = value.astimezone(tzinfo)

    def truncate(value, kind):
        if kind == 'second':
            return value.replace(microsecond=0)
        if kind == 'minute':
            return value.replace(second=0, microsecond=0)
        if kind == 'hour':
            return value.replace(minute=0, second=0, microsecond=0)
        if kind == 'day':
            if isinstance(value, datetime):
                return value.replace(hour=0, minute=0, second=0, microsecond=0)
            return value
        if kind == 'month':
            if isinstance(value, datetime):
                return value.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            return value.replace(day=1)
        if kind == 'quarter':
            month_in_quarter = value.month - (value.month - 1) % 3
            if isinstance(value, datetime):
                return value.replace(month=month_in_quarter, day=1, hour=0, minute=0, second=0, microsecond=0)
            return value.replace(month=month_in_quarter, day=1)
        # otherwise, truncate to year
        if isinstance(value, datetime):
            return value.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        return value.replace(month=1, day=1)

    value = truncate(value, kind)
    return value


@override_settings(USE_TZ=False)
class DateFunctionTests(TestCase):

    def create_model(self, start_datetime, end_datetime):
        return DTModel.objects.create(
            name=start_datetime.isoformat(),
            start_datetime=start_datetime, end_datetime=end_datetime,
            start_date=start_datetime.date(), end_date=end_datetime.date(),
            start_time=start_datetime.time(), end_time=end_datetime.time(),
            duration=(end_datetime - start_datetime),
        )

    def test_extract_year_exact_lookup(self):
        """
        Extract year uses a BETWEEN filter to compare the year to allow indexes
        to be used.
        """
        start_datetime = datetime(2015, 6, 15, 14, 10)
        end_datetime = datetime(2016, 6, 15, 14, 10)
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)

        qs = DTModel.objects.filter(start_datetime__year__exact=2015)
        self.assertEqual(qs.count(), 1)
        query_string = str(qs.query).lower()
        self.assertEqual(query_string.count(' between '), 1)
        self.assertEqual(query_string.count('extract'), 0)

        # exact is implied and should be the same
        qs = DTModel.objects.filter(start_datetime__year=2015)
        self.assertEqual(qs.count(), 1)
        query_string = str(qs.query).lower()
        self.assertEqual(query_string.count(' between '), 1)
        self.assertEqual(query_string.count('extract'), 0)

        # date and datetime fields should behave the same
        qs = DTModel.objects.filter(start_date__year=2015)
        self.assertEqual(qs.count(), 1)
        query_string = str(qs.query).lower()
        self.assertEqual(query_string.count(' between '), 1)
        self.assertEqual(query_string.count('extract'), 0)

    def test_extract_year_greaterthan_lookup(self):
        start_datetime = datetime(2015, 6, 15, 14, 10)
        end_datetime = datetime(2016, 6, 15, 14, 10)
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)

        qs = DTModel.objects.filter(start_datetime__year__gt=2015)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(str(qs.query).lower().count('extract'), 0)
        qs = DTModel.objects.filter(start_datetime__year__gte=2015)
        self.assertEqual(qs.count(), 2)
        self.assertEqual(str(qs.query).lower().count('extract'), 0)

    def test_extract_year_lessthan_lookup(self):
        start_datetime = datetime(2015, 6, 15, 14, 10)
        end_datetime = datetime(2016, 6, 15, 14, 10)
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)

        qs = DTModel.objects.filter(start_datetime__year__lt=2016)
        self.assertEqual(qs.count(), 1)
        self.assertEqual(str(qs.query).count('extract'), 0)
        qs = DTModel.objects.filter(start_datetime__year__lte=2016)
        self.assertEqual(qs.count(), 2)
        self.assertEqual(str(qs.query).count('extract'), 0)

    def test_extract_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)

        with self.assertRaisesMessage(ValueError, 'lookup_name must be provided'):
            Extract('start_datetime')

        msg = 'Extract input expression must be DateField, DateTimeField, TimeField, or DurationField.'
        with self.assertRaisesMessage(ValueError, msg):
            list(DTModel.objects.annotate(extracted=Extract('name', 'hour')))

        with self.assertRaisesMessage(
                ValueError, "Cannot extract time component 'second' from DateField 'start_date'."):
            list(DTModel.objects.annotate(extracted=Extract('start_date', 'second')))

        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'year')).order_by('start_datetime'),
            [(start_datetime, start_datetime.year), (end_datetime, end_datetime.year)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'quarter')).order_by('start_datetime'),
            [(start_datetime, 2), (end_datetime, 2)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'month')).order_by('start_datetime'),
            [(start_datetime, start_datetime.month), (end_datetime, end_datetime.month)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'day')).order_by('start_datetime'),
            [(start_datetime, start_datetime.day), (end_datetime, end_datetime.day)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'week')).order_by('start_datetime'),
            [(start_datetime, 25), (end_datetime, 24)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'week_day')).order_by('start_datetime'),
            [
                (start_datetime, (start_datetime.isoweekday() % 7) + 1),
                (end_datetime, (end_datetime.isoweekday() % 7) + 1)
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'hour')).order_by('start_datetime'),
            [(start_datetime, start_datetime.hour), (end_datetime, end_datetime.hour)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'minute')).order_by('start_datetime'),
            [(start_datetime, start_datetime.minute), (end_datetime, end_datetime.minute)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('start_datetime', 'second')).order_by('start_datetime'),
            [(start_datetime, start_datetime.second), (end_datetime, end_datetime.second)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__year=Extract('start_datetime', 'year')).count(), 2)
        self.assertEqual(DTModel.objects.filter(start_datetime__hour=Extract('start_datetime', 'hour')).count(), 2)
        self.assertEqual(DTModel.objects.filter(start_date__month=Extract('start_date', 'month')).count(), 2)
        self.assertEqual(DTModel.objects.filter(start_time__hour=Extract('start_time', 'hour')).count(), 2)

    @skipUnlessDBFeature('has_native_duration_field')
    def test_extract_duration(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=Extract('duration', 'second')).order_by('start_datetime'),
            [
                (start_datetime, (end_datetime - start_datetime).seconds % 60),
                (end_datetime, (start_datetime - end_datetime).seconds % 60)
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(
            DTModel.objects.annotate(
                duration_days=Extract('duration', 'day'),
            ).filter(duration_days__gt=200).count(),
            1
        )

    @skipIfDBFeature('has_native_duration_field')
    def test_extract_duration_without_native_duration_field(self):
        msg = 'Extract requires native DurationField database support.'
        with self.assertRaisesMessage(ValueError, msg):
            list(DTModel.objects.annotate(extracted=Extract('duration', 'second')))

    def test_extract_year_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractYear('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.year), (end_datetime, end_datetime.year)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractYear('start_date')).order_by('start_datetime'),
            [(start_datetime, start_datetime.year), (end_datetime, end_datetime.year)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__year=ExtractYear('start_datetime')).count(), 2)

    def test_extract_month_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractMonth('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.month), (end_datetime, end_datetime.month)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractMonth('start_date')).order_by('start_datetime'),
            [(start_datetime, start_datetime.month), (end_datetime, end_datetime.month)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__month=ExtractMonth('start_datetime')).count(), 2)

    def test_extract_day_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractDay('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.day), (end_datetime, end_datetime.day)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractDay('start_date')).order_by('start_datetime'),
            [(start_datetime, start_datetime.day), (end_datetime, end_datetime.day)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__day=ExtractDay('start_datetime')).count(), 2)

    def test_extract_week_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractWeek('start_datetime')).order_by('start_datetime'),
            [(start_datetime, 25), (end_datetime, 24)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractWeek('start_date')).order_by('start_datetime'),
            [(start_datetime, 25), (end_datetime, 24)],
            lambda m: (m.start_datetime, m.extracted)
        )
        # both dates are from the same week.
        self.assertEqual(DTModel.objects.filter(start_datetime__week=ExtractWeek('start_datetime')).count(), 2)

    def test_extract_quarter_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 8, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractQuarter('start_datetime')).order_by('start_datetime'),
            [(start_datetime, 2), (end_datetime, 3)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractQuarter('start_date')).order_by('start_datetime'),
            [(start_datetime, 2), (end_datetime, 3)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__quarter=ExtractQuarter('start_datetime')).count(), 2)

    def test_extract_quarter_func_boundaries(self):
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))

        last_quarter_2014 = microsecond_support(datetime(2014, 12, 31, 13, 0))
        first_quarter_2015 = microsecond_support(datetime(2015, 1, 1, 13, 0))
        dates = [last_quarter_2014, first_quarter_2015]
        self.create_model(last_quarter_2014, end_datetime)
        self.create_model(first_quarter_2015, end_datetime)
        qs = DTModel.objects.filter(start_datetime__in=dates).annotate(
            extracted=ExtractQuarter('start_datetime'),
        ).order_by('start_datetime')
        self.assertQuerySetEqual(qs, [
            (last_quarter_2014, 4),
            (first_quarter_2015, 1),
        ], lambda m: (m.start_datetime, m.extracted))

    def test_extract_week_func_boundaries(self):
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))

        week_52_day_2014 = microsecond_support(datetime(2014, 12, 27, 13, 0))  # Sunday
        week_1_day_2014_2015 = microsecond_support(datetime(2014, 12, 31, 13, 0))  # Wednesday
        week_53_day_2015 = microsecond_support(datetime(2015, 12, 31, 13, 0))  # Thursday

        days = [week_52_day_2014, week_1_day_2014_2015, week_53_day_2015]
        self.create_model(week_53_day_2015, end_datetime)
        self.create_model(week_52_day_2014, end_datetime)
        self.create_model(week_1_day_2014_2015, end_datetime)
        qs = DTModel.objects.filter(start_datetime__in=days).annotate(
            extracted=ExtractWeek('start_datetime'),
        ).order_by('start_datetime')
        self.assertQuerySetEqual(qs, [
            (week_52_day_2014, 52),
            (week_1_day_2014_2015, 1),
            (week_53_day_2015, 53),
        ], lambda m: (m.start_datetime, m.extracted))

    def test_extract_weekday_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractWeekDay('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, (start_datetime.isoweekday() % 7) + 1),
                (end_datetime, (end_datetime.isoweekday() % 7) + 1),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractWeekDay('start_date')).order_by('start_datetime'),
            [
                (start_datetime, (start_datetime.isoweekday() % 7) + 1),
                (end_datetime, (end_datetime.isoweekday() % 7) + 1),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__week_day=ExtractWeekDay('start_datetime')).count(), 2)

    def test_extract_hour_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractHour('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.hour), (end_datetime, end_datetime.hour)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractHour('start_time')).order_by('start_datetime'),
            [(start_datetime, start_datetime.hour), (end_datetime, end_datetime.hour)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__hour=ExtractHour('start_datetime')).count(), 2)

    def test_extract_minute_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractMinute('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.minute), (end_datetime, end_datetime.minute)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractMinute('start_time')).order_by('start_datetime'),
            [(start_datetime, start_datetime.minute), (end_datetime, end_datetime.minute)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__minute=ExtractMinute('start_datetime')).count(), 2)

    def test_extract_second_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractSecond('start_datetime')).order_by('start_datetime'),
            [(start_datetime, start_datetime.second), (end_datetime, end_datetime.second)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=ExtractSecond('start_time')).order_by('start_datetime'),
            [(start_datetime, start_datetime.second), (end_datetime, end_datetime.second)],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__second=ExtractSecond('start_datetime')).count(), 2)

    def test_trunc_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)

        msg = 'output_field must be either DateField, TimeField, or DateTimeField'
        with self.assertRaisesMessage(ValueError, msg):
            list(DTModel.objects.annotate(truncated=Trunc('start_datetime', 'year', output_field=IntegerField())))

        with self.assertRaisesMessage(AssertionError, "'name' isn't a DateField, TimeField, or DateTimeField."):
            list(DTModel.objects.annotate(truncated=Trunc('name', 'year', output_field=DateTimeField())))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=Trunc('start_date', 'second')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=Trunc('start_time', 'month')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=Trunc('start_date', 'month', output_field=DateTimeField())))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=Trunc('start_time', 'second', output_field=DateTimeField())))

        def test_datetime_kind(kind):
            self.assertQuerySetEqual(
                DTModel.objects.annotate(
                    truncated=Trunc('start_datetime', kind, output_field=DateTimeField())
                ).order_by('start_datetime'),
                [
                    (start_datetime, truncate_to(start_datetime, kind)),
                    (end_datetime, truncate_to(end_datetime, kind))
                ],
                lambda m: (m.start_datetime, m.truncated)
            )

        def test_date_kind(kind):
            self.assertQuerySetEqual(
                DTModel.objects.annotate(
                    truncated=Trunc('start_date', kind, output_field=DateField())
                ).order_by('start_datetime'),
                [
                    (start_datetime, truncate_to(start_datetime.date(), kind)),
                    (end_datetime, truncate_to(end_datetime.date(), kind))
                ],
                lambda m: (m.start_datetime, m.truncated)
            )

        def test_time_kind(kind):
            self.assertQuerySetEqual(
                DTModel.objects.annotate(
                    truncated=Trunc('start_time', kind, output_field=TimeField())
                ).order_by('start_datetime'),
                [
                    (start_datetime, truncate_to(start_datetime.time(), kind)),
                    (end_datetime, truncate_to(end_datetime.time(), kind))
                ],
                lambda m: (m.start_datetime, m.truncated)
            )

        test_date_kind('year')
        test_date_kind('quarter')
        test_date_kind('month')
        test_date_kind('day')
        test_time_kind('hour')
        test_time_kind('minute')
        test_time_kind('second')
        test_datetime_kind('year')
        test_datetime_kind('quarter')
        test_datetime_kind('month')
        test_datetime_kind('day')
        test_datetime_kind('hour')
        test_datetime_kind('minute')
        test_datetime_kind('second')

        qs = DTModel.objects.filter(start_datetime__date=Trunc('start_datetime', 'day', output_field=DateField()))
        self.assertEqual(qs.count(), 2)

    def test_trunc_year_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'year')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncYear('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'year')),
                (end_datetime, truncate_to(end_datetime, 'year')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncYear('start_date')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.date(), 'year')),
                (end_datetime, truncate_to(end_datetime.date(), 'year')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncYear('start_datetime')).count(), 1)

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncYear('start_time')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncYear('start_time', output_field=TimeField())))

    def test_trunc_quarter_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 10, 15, 14, 10, 50, 123)), 'quarter')
        last_quarter_2015 = truncate_to(microsecond_support(datetime(2015, 12, 31, 14, 10, 50, 123)), 'quarter')
        first_quarter_2016 = truncate_to(microsecond_support(datetime(2016, 1, 1, 14, 10, 50, 123)), 'quarter')
        self.create_model(start_datetime=start_datetime, end_datetime=end_datetime)
        self.create_model(start_datetime=end_datetime, end_datetime=start_datetime)
        self.create_model(start_datetime=last_quarter_2015, end_datetime=end_datetime)
        self.create_model(start_datetime=first_quarter_2016, end_datetime=end_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncQuarter('start_date')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.date(), 'quarter')),
                (last_quarter_2015, truncate_to(last_quarter_2015.date(), 'quarter')),
                (first_quarter_2016, truncate_to(first_quarter_2016.date(), 'quarter')),
                (end_datetime, truncate_to(end_datetime.date(), 'quarter')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncQuarter('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'quarter')),
                (last_quarter_2015, truncate_to(last_quarter_2015, 'quarter')),
                (first_quarter_2016, truncate_to(first_quarter_2016, 'quarter')),
                (end_datetime, truncate_to(end_datetime, 'quarter')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncQuarter('start_time')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncQuarter('start_time', output_field=TimeField())))

    def test_trunc_month_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'month')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncMonth('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'month')),
                (end_datetime, truncate_to(end_datetime, 'month')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncMonth('start_date')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.date(), 'month')),
                (end_datetime, truncate_to(end_datetime.date(), 'month')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncMonth('start_datetime')).count(), 1)

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncMonth('start_time')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncMonth('start_time', output_field=TimeField())))

    def test_trunc_date_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncDate('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, start_datetime.date()),
                (end_datetime, end_datetime.date()),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__date=TruncDate('start_datetime')).count(), 2)

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateField"):
            list(DTModel.objects.annotate(truncated=TruncDate('start_time')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateField"):
            list(DTModel.objects.annotate(truncated=TruncDate('start_time', output_field=TimeField())))

    def test_trunc_time_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123))
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncTime('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, start_datetime.time()),
                (end_datetime, end_datetime.time()),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime__time=TruncTime('start_datetime')).count(), 2)

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to TimeField"):
            list(DTModel.objects.annotate(truncated=TruncTime('start_date')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to TimeField"):
            list(DTModel.objects.annotate(truncated=TruncTime('start_date', output_field=DateField())))

    def test_trunc_day_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'day')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncDay('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'day')),
                (end_datetime, truncate_to(end_datetime, 'day')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncDay('start_datetime')).count(), 1)

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncDay('start_time')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate TimeField 'start_time' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncDay('start_time', output_field=TimeField())))

    def test_trunc_hour_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'hour')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncHour('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'hour')),
                (end_datetime, truncate_to(end_datetime, 'hour')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncHour('start_time')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.time(), 'hour')),
                (end_datetime, truncate_to(end_datetime.time(), 'hour')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncHour('start_datetime')).count(), 1)

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncHour('start_date')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncHour('start_date', output_field=DateField())))

    def test_trunc_minute_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'minute')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncMinute('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'minute')),
                (end_datetime, truncate_to(end_datetime, 'minute')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncMinute('start_time')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.time(), 'minute')),
                (end_datetime, truncate_to(end_datetime.time(), 'minute')),
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncMinute('start_datetime')).count(), 1)

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncMinute('start_date')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncMinute('start_date', output_field=DateField())))

    def test_trunc_second_func(self):
        start_datetime = microsecond_support(datetime(2015, 6, 15, 14, 30, 50, 321))
        end_datetime = truncate_to(microsecond_support(datetime(2016, 6, 15, 14, 10, 50, 123)), 'second')
        self.create_model(start_datetime, end_datetime)
        self.create_model(end_datetime, start_datetime)
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncSecond('start_datetime')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime, 'second')),
                (end_datetime, truncate_to(end_datetime, 'second'))
            ],
            lambda m: (m.start_datetime, m.extracted)
        )
        self.assertQuerySetEqual(
            DTModel.objects.annotate(extracted=TruncSecond('start_time')).order_by('start_datetime'),
            [
                (start_datetime, truncate_to(start_datetime.time(), 'second')),
                (end_datetime, truncate_to(end_datetime.time(), 'second'))
            ],
            lambda m: (m.start_datetime, m.extracted)
        )

        result = 1 if connection.features.supports_microsecond_precision else 2
        self.assertEqual(DTModel.objects.filter(start_datetime=TruncSecond('start_datetime')).count(), result)

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncSecond('start_date')))

        with self.assertRaisesMessage(ValueError, "Cannot truncate DateField 'start_date' to DateTimeField"):
            list(DTModel.objects.annotate(truncated=TruncSecond('start_date', output_field=DateField())))

