# Databricks notebook source
pip install sap-bdc-connect-sdk
 
# COMMAND ----------
 
pip show sap-bdc-connect-sdk
 
# COMMAND ----------
 
# Create deltashare beforehand in databricks then create data product in internal datalake for datashpere
from bdc_connect_sdk.auth import BdcConnectClient
from bdc_connect_sdk.auth import DatabricksClient
 
bdc_connect_client = BdcConnectClient(DatabricksClient(dbutils, "sap-business-data-cloud"))
 
share_name = "cumulocity_minimal"
 
open_resource_discovery_information = {
    "@openResourceDiscoveryV1": {
        "title": "cumulocity_temp_and_position",
        "shortDescription": "Cumulocity Temprature and Geopositions",
        "description": "PoC to server Cumulocity Temprature values and Geopositions",
        "version": "1.0.1",
        "releaseStatus": "active",
        "visibility": "public",
        "dataProducts": [
            {
                "ordId": "sap.databricks:dataProduct:cumulocity_temp_and_position:v1",
                "title": "cumulocity_temp_and_position",
                "shortDescription": "Cumulocity Temprature and Geopositions",
                "description": "PoC to server Cumulocity Temprature values and Geopositions",
                "version": "1.0.1",        # ← this is what the catalog displays
                "releaseStatus": "active",
                "visibility": "public"
            }
        ]
    }
}
 
bdc_connect_client.create_or_update_share(
    share_name,
    open_resource_discovery_information
)
 
# COMMAND ----------
 
 
# Create schema for odata api in internal datalake for datashpere to read, Will faile if tables are not suitable
from bdc_connect_sdk.auth import BdcConnectClient
from bdc_connect_sdk.auth import DatabricksClient
from bdc_connect_sdk.utils import csn_generator
 
bdc_connect_client = BdcConnectClient(DatabricksClient(dbutils, "sap-business-data-cloud"))
 
share_name = "cumulocity_minimal"
 
# could use manual csn generation here. Works only if schema fits
csn_schema = csn_generator.generate_csn_template(share_name)
 
bdc_connect_client.create_or_update_share_csn(
    share_name,
    csn_schema
)
 
# COMMAND ----------
 
# Publish data product
from bdc_connect_sdk.auth import BdcConnectClient
from bdc_connect_sdk.auth import DatabricksClient
 
bdc_connect_client = BdcConnectClient(DatabricksClient(dbutils, "sap-business-data-cloud"))
 
share_name = "cumulocity_minimal"
 
bdc_connect_client.publish_data_product(
    share_name
)
