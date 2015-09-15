LDS BDE Loader
===================

A tool for managing the regular updates of [LINZ property ownership and boundary data](http://www.linz.govt.nz/data/linz-data/property-ownership-and-boundary-data/types-lds-property-ownership-and-boundary-data) (formerly BDE) into the [LINZ Data Service](https://data.linz.govt.nz) via the Koordinates APIs.

Open Source Software released under the BSD License.

The full process for updating Landonline data into the LINZ Data Service is:

1. Regular daily incremental & monthly full data dumps are produced from the LINZ Landonline system.
2. The dumps are processed daily by [linz_bde_uploader](https://github.com/linz/linz_bde_uploader) into a PostgreSQL database. Cleans some data, maintains versioned datasets, and creates simplified datasets.
3. The process triggers this lds-bde-loader tool, which manages data updates into the LINZ Data Service from the PostgreSQL database, performs consistency checks, and publishes updates. Currently this runs weekly. Support tools are also available to manage updates.
4. Updated datasets are available via downloads, APIs, and web services from the LINZ Data Service.

Installation
------------

Inside a virtualenv environment:
```
$ pip install -r requirements.txt
$ pip install -e .
```

Configuration
-------------

Running `lds-bde-loader init` will prompt for some information relating to the Koordinates system, create API credentials for the updates, and sets some defaults.

If this installation is running _on_ the BDE processor, some additional configuration is required:

* Edit the created configuration file, and uncomment the `bde` section:
  * set database access details.
  * add details on BDE processor table names and Koordinates Layer IDs to update.
  * group layers together into publish groups.
  * set update schedules.
* Edit the created configuration file, and update the `logging` section to configure file logging.
* Create a Cron job: run `lds-bde-loader cron-monitor --help` for details.
* Configure the BDE processor to run the event hooks:
  * Ensure any BDE processor Cron tasks are running with the `-event-hooks` flag.
  * Configure the event hooks in `/etc/linz-bde-uploader/linz_bde_uploader.conf`: Run `linz-bde-uploader process-start --help`, `linz-bde-uploader process-finish --help`, and `linz-bde-uploader process-error --help` to see details on the required configuration stanzas.

Usage
-----

Run `lds-bde-loader --help` for details on available commands.
