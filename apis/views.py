from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.core.files import File

import datetime
import pandas as pd
import s3fs
from statsmodels.tsa.arima.model import ARIMA

from .models import Case

def generate_forecast(series):
    # generate training and testing data
    seventy_percent = int(((len(series)) / 10) * 7.5)
    train = series[:seventy_percent]
    test = series[seventy_percent:]

    # fit model
    initial_model = ARIMA(train, order=(1,1,1), freq="M").fit()
    final_model = ARIMA(series, order=(1,1,1), freq="M").fit()

    # get validation and residuals
    validation = pd.Series(initial_model.forecast(len(test)))
    residuals = test - validation

    # forecast
    forecast = pd.Series(final_model.forecast(12), name='Forecast')

    return {
        "actual": {
            "name": "Actual",
            "startDate": [series.index[0].year, series.index[0].month, series.index[0].day],
            "cases": series.tolist(),
        },
        "validation" : {
            "name": "Validation",
            "startDate": [validation.index[0].year, validation.index[0].month],
            "cases": validation.tolist(),
        },
        "residuals": {
            "name": "Residuals",
            "startDate": [residuals.index[0].year, residuals.index[0].month],
            "cases": residuals.tolist()
        },
        "forecast": {
            "name": "Forecast",
            "startDate": [forecast.index[0].year, forecast.index[0].month],
            "cases": forecast.tolist()
        }
    }

@api_view(['GET', 'POST'])
def forecast(request):
    # read data, convert to pd.Series, and add date index
    series = []
    if request.method == 'GET':
        recent_case = Case.objects.all().first()
        csv_file_path = recent_case.csv_file.url
        series = pd.read_csv(csv_file_path)
        series = series.iloc[:, 0]
        series.index = pd.date_range(start=recent_case.start_date, periods=len(series), freq='M')

    elif request.method == 'POST':
        series = pd.Series(request.data['cases'])
        start_date = datetime.datetime.strptime("{}-{}-{}".format(request.data['startDate'][0], request.data['startDate'][1], request.data['startDate'][2]), '%Y-%m-%d').date()
        series.index = pd.date_range(start=start_date , periods=len(request.data['cases']), freq='M')

    data = generate_forecast(series)
    return Response(data)

@api_view(['POST'])
@permission_classes((IsAuthenticated, ))
def update_table(request):
    try:
        series = pd.Series([int(value) for value in request.data['cases']], name='Cases')
        start_date = datetime.datetime.strptime(request.data['startDate'], '%Y-%m-%d').date()
        
        series.to_csv("csv-files/new.csv", index=False)
        f = open('csv-files/new.csv')
        myfile = File(f)

    except ValueError:
        return Response(status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

    new_record = Case(start_date=start_date)
    new_record.csv_file.save("new.csv", myfile)
    new_record.save()

    # the same from GET method in forecast view
    recent_case = Case.objects.all().first()
    csv_file_path = recent_case.csv_file.url
    series = pd.read_csv(csv_file_path[1:])
    series = series.iloc[:, 0]
    series.index = pd.date_range(start=recent_case.start_date, periods=len(series), freq='M')

    data = generate_forecast(series)
    return Response(data)