from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django.core.files import File

import s3fs
import boto3
from io import StringIO 

import datetime
import pandas as pd
from statsmodels.tsa.arima.model import ARIMA
from statsmodels.tsa.statespace.sarimax import SARIMAX
from sklearn.metrics import mean_absolute_error, mean_squared_error, mean_absolute_percentage_error

from .models import Case

def generate_forecast(series):
    series_raw = series.copy()
    series_raw = series_raw.fillna('NaN')

    series_processed = series.copy()
    series_processed = series_processed.ffill()

    # generate training and testing data
    seventy_percent = int(((len(series_processed)) / 10) * 7.5)
    train = series_processed[:seventy_percent]
    test = series_processed[seventy_percent:]

    # fit model
    initial_model = ARIMA(train, order=(2,1,0)).fit()
    final_model = SARIMAX(series_processed, order=(2,1,0)).fit()

    # predict
    predict = final_model.predict()

    # get validation, residuals
    validation = pd.Series(initial_model.forecast(len(test)))
    residuals = test - validation
    
    # get performance measeures
    mae = mean_absolute_error(series_processed, predict)
    mse = mean_squared_error(series_processed, predict, squared=False)
    mape = mean_absolute_percentage_error(series_processed, predict)

    # forecast
    forecast = pd.Series(final_model.forecast(12), name='Forecast')

    return {
        "raw": {
            "name": "Raw",
            "startDate": [series_raw.index[0].year, series_raw.index[0].month, series_raw.index[0].day],
            "cases": series_raw.tolist(),
        },
        "actual": {
            "name": "Actual",
            "startDate": [series_processed.index[0].year, series_processed.index[0].month, series_processed.index[0].day],
            "cases": series_processed.tolist(),
        },
        "predict": {
            "cases": final_model.predict()
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
        },
        "performanceMeasures": {
            "mae": round(mae, 2),
            "mse": round(mse, 2),
            "mape": round(mape * 100, 2) 
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
        series = pd.Series([int(value) if value else None for value in request.data['cases']], name='Cases')
        start_date = datetime.datetime.strptime("{}-{}-{}".format(request.data['startDate'][0], request.data['startDate'][1], request.data['startDate'][2]), '%Y-%m-%d').date()
        series.index = pd.date_range(start=start_date , periods=len(request.data['cases']), freq='M')

    data = generate_forecast(series)
    return Response({"raw": data["raw"], "actual": data["actual"], "forecast": data["forecast"]})

@api_view(['GET', 'POST'])
@permission_classes((IsAuthenticated, ))
def update_table(request):
    if request.method == 'POST':
        try:
            series = pd.Series([int(value) if value else None for value in request.data['cases']], name='Cases')
            start_date = datetime.datetime.strptime(request.data['startDate'], '%Y-%m-%d').date()

            bucket = "hiv-forecasting-ph-bucket"
            csv_buffer = StringIO()
            series.to_csv(csv_buffer, index=False)

            s3_resource = boto3.resource('s3')
            s3_resource.Object(bucket, 'series.csv').put(Body=csv_buffer.getvalue())
            s3_resource.Bucket(bucket).download_file('series.csv', 'static/series.csv')
            f = open('static/series.csv', "rb")
            myfile = File(f)

        except ValueError:
            return Response(status=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)

        new_record = Case(start_date=start_date)
        new_record.csv_file.save("series.csv", myfile)
        new_record.save()

    # the same from GET method in forecast view
    recent_case = Case.objects.all().first()
    csv_file_path = recent_case.csv_file.url
    series = pd.read_csv(csv_file_path)
    series = series.iloc[:, 0]
    series.index = pd.date_range(start=recent_case.start_date, periods=len(series), freq='M')

    data = generate_forecast(series)
    return Response({   "raw": data["raw"], 
                        "actual": data["actual"], 
                        "validation": data["validation"],
                        "forecast": data["forecast"],
                        "residuals": data["residuals"], 
                        "performanceMeasures": data["performanceMeasures"]
                    })