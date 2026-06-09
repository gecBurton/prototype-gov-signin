web: cd iam && gunicorn wsgi:application --bind 0.0.0.0:$PORT
release: cd iam && python manage.py migrate --noinput && python manage.py collectstatic --noinput
