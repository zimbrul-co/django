DATABASES = {
    'default': {
        'ENGINE': 'django_cubrid',
        'NAME': 'django',
        'USER': 'public',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '33000',
    },
    'other': {
        'ENGINE': 'django_cubrid',
        'NAME': 'django_oth',
        'USER': 'public',
        'PASSWORD': '',
        'HOST': 'localhost',
        'PORT': '33000',
    }
}

SECRET_KEY = "django_tests_secret_key"

# Use a fast hasher to speed up tests.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
