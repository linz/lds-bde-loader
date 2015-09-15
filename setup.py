from setuptools import setup, find_packages

import ldsbde

setup(name='lds-bde-loader',
    version='0.2.%s' % (ldsbde.__build__ or 'dev'),
    description="LINZ LDS BDE Loader",
    long_description="Tool for managing the regular updates of the LINZ BDE data into the LINZ Data Service",
    classifiers=[],
    keywords='',
    author='Koordinates Limited',
    author_email='support@koordinates.com',
    url='https://github.com/koordinates/lds-bde-loader',
    license='BSD',
    packages=find_packages(exclude=['ez_setup', 'examples', 'tests']),
    include_package_data=True,
    zip_safe=False,
    test_suite='nose.collector',
    install_requires=[
        ### Required for testing
        "nose",
        "coverage",
        ### Required to function
        'click',
        'click-plugins',
        'koordinates',
        'python-dateutil',
        'psycopg2',
        'PyYAML',
        'slacker',
    ],
    setup_requires=[],
    entry_points="""
        [console_scripts]
        lds-bde-loader = ldsbde.cli.main:main

        [ldsbde.commands]
        init = ldsbde.cli.init:init
        bde-current = ldsbde.cli.support:bde_current
        show = ldsbde.cli.support:show
        check-import = ldsbde.cli.support:check_import
        start-import = ldsbde.cli.support:start_import
        continue-import = ldsbde.cli.support:continue_import
        error-email = ldsbde.cli.support:error_email
        process-start = ldsbde.cli.process:start
        process-finish = ldsbde.cli.process:finish
        process-error = ldsbde.cli.process:error
        cron-monitor = ldsbde.cli.support:cron_monitor
    """,
    namespace_packages=[],
)
