""" :module PseudomonasDotComScraper: Hosting the PseudomonasDotComScraper, an API for the https://www.pseudomonas.com database web interface. """

# 3rd party imports
from bs4 import BeautifulSoup
from collections import namedtuple
from contextlib import closing
from pandas import DataFrame, read_html
from requests import get
from requests.exceptions import RequestException
import bs4
import re

# Define the query datastructure.
pdc_query = namedtuple('pdc_query',
        field_names=('strain', 'feature', 'organism'),
        defaults=(None, None, None),
        )

class PseudomonasDotComScraper():
    """  An API for the pseudomonas.com genome database using web scraping technology. """

    # Class constructor
    def __init__(self,
            query=None,
            feature=None,
            ):
        """
        PseudomonasDotComScraper constructor.

        :param query: The query to submit to the database.
        :type query: (pdc_query || dict)

        :example: scraper = PseudomonasDotComScraper(query={'strain' : 'sbw25', 'feature' : 'pflu0916'})
        :example: scraper = PseudomonasDotComScraper(query=pdc_query(strain='sbw25', feature='pflu0916'))

        """

        # Base class initialization.
        #super(<+ClassName+>).__init__(<+base_class_args+>)

        # Initialize all variables.
        self.__query = None
        self.__pdc_url = 'https://www.pseudomonas.com'
        self.__browser = None
        self.__connected = False

        # Set attributes via setter.
        self.query = query

    # Attribute accessors
    @property
    def connected(self):
        return self.__connected

    @property
    def query(self):
        """ Get the query.

        :return: The strings to query the database.
        :rtype:  str

        """

        return self.__query

    @query.setter
    def query(self, val):
        """"""
        """ Set the query attribute.

        :param val: The value to set.
        :type val: str

        :raises KeyError: Both 'strain' and 'organism' are provided.
        """

        # Checks
        if val is None:
            val = pdc_query(strain='sbw25')

        if not isinstance(val, (dict, pdc_query)):
            raise TypeError("The parameter 'query' must be a dict or pdc_query. Examples: query={'strain' : 'sbw25', 'feature'='pflu0916'}; query=pdc_query(strain='sbw25', feature='pflu0916').")

        # Check keys if dict.
        if isinstance(val, dict):
            # Only these are acceptable query keywords.
            accepted_keys = ('strain', 'feature', 'organism')
            present_keys = val.keys()
            for k in present_keys:
                if not k in accepted_keys:
                    raise KeyError("Only 'strain', 'feature', and 'organism' are acceptable keys.)")

            # Complete keywords.
            if not 'strain' in val.keys():
                val['strain'] = None
            if not 'feature' in val.keys():
                val['feature'] = None
            if not 'organism' in val.keys():
                val['organism'] = None

            # Convert to pdc_query
            print('INFO: Query dictionary passed to pseudomonas.com scraper will now be converted to a pdc_query object. See reference manual for more details.')
            val = _dict_to_pdc_query(**val)

        # Check keywords are internally consistent.
        if val.organism is not None and val.strain is not None:
            raise KeyError("Invalid combination of query keywords: 'organism' must not be combined with 'strain'.")

        # Check all values are strings or None.
        for v in val[:]:
            if not (isinstance(v, str) or v is None):
                raise TypeError("All values in the query must be of type str.")
        self.__query = val

    def connect(self):
        """ Connect to the database. """
        try:
            self.__browser = BeautifulSoup(_simple_get(self.__pdc_url), 'html.parser')
        except:
            self.__connected = False
            raise ConnectionError("Connecting to {0:s} failed. Make sure the URL is set correctly and is reachable.")

        self.__connected = True


    def run_query(self, query=None):
        """ Submit a query to the db and get results.

        :param query: (Optional) the query object to submit.
        :type  query: pdc_query
        """

        # Check if we're connected. Bail out if not.
        if not self.__connected:
            raise RuntimeError("Not connected. Call .connect() before submitting the query.")

        # If provided, update the local query object. This way, user can submit a query at run time.
        if query is not None:
            self.query = query

        # Form http self.query string.
        _feature = self.query.feature
        if _feature is None:
            _feature = ''

        # Assemble the html query.
        if self.query.strain is not None: # Searching for specific strain.
            _url = self.__pdc_url+"/primarySequenceFeature/list?c1=name&v1={0:s}&e1=1&term1={1:s}&assembly=complete".format(_feature, self.query.strain)
        elif self.query.organism is not None: # Searching for organism.
            _url = self.__pdc_url+"/primarySequenceFeature/list?c1=name&v1={0:s}&e1=1&term2={1:s}&assembly=complete".format(_feature, self.query.organism)

        # Debug info.
        print("DEBUG: Will now open {0:s}".format(_url))

        # Get the soup for the assembled url.
        browser = BeautifulSoup(_simple_get(_url), 'html.parser')

        # If we're looking for a unique feature.
        if _feature is not '':
            feature_link = browser.find_all('a', string=re.compile(_feature.upper()))[0].get('href')

        # Prepend base url.
        feature_link = self.__pdc_url+feature_link
        # Get the soup.
        browser = BeautifulSoup(_simple_get(feature_link), 'html.parser')

        # Setup dict to store self.query results.
        panels = dict()

        # Loop over headings and get table as pandas.DataFrame.
        for heading in ["Gene Feature Overview",
                        "Cross-References",
                        "Product",
                        "Subcellular localization",
                        "Pathogen Association Analysis",
                        "Orthologs/Comparative Genomics",
                        "Interactions",
                        ]:
            panels[heading] = _pandasDF_from_heading(browser, heading)
            panels["References"] = _pandasDF_from_heading(browser, '^References') # to disambiguate from Cross-References

        # Assemble url for functions (tab "Function/Pathways/GO")
        function_url = feature_link + "&view=functions"
        browser = BeautifulSoup(_simple_get(function_url), 'html.parser')

        for heading in [
                "Gene Ontology",
                "Functional Classifications Manually Assigned by PseudoCAP",
                "Functional Predictions from Interpro",
                ]:
            panels[heading] = _pandasDF_from_heading(browser, heading)

        # Return.
        return panels
# Helper functions for handling urls.

def _simple_get(url):
    """ """
    """ Get content of passed URL to pass on to BeautifulSoup.

    :param url: The URL to parse.
    :type  url: str

    """

    # Safeguard opening the URL.
    with closing(get(url, stream=True)) as resp:
        if _is_good_response(resp):
            print("INFO: Good response from "+url+".")
            return resp.content
        else:
            raise RuntimeError("ERROR: Could not open "+url+".")

def _is_good_response(resp):
    """ """
    """ Returns True if the response seems to be HTML, False otherwise.

    :param resp: The response to validate.
    :type  resp: http response as returned from contextlib.closing

    """

    content_type = resp.headers['Content-Type'].lower()
    return (resp.status_code == 200
            and content_type is not None
            and content_type.find('html') > -1)


def _dict_to_pdc_query(**kwargs):
    """ """
    """
    Convert a dictionary of query key-value pairs to a pdc_query instance.

    :param kwargs: Dictionary of query key-value pairs.
    :type kwargs: dict
    """

    query = pdc_query(kwargs['strain'], kwargs['feature'], kwargs['organism'])

    return query

def _pandasDF_from_heading(soup, table_heading):
    """ """
    """ Find the table that belongs to the passed heading in a formatted html tree (the soup).

    :param soup: The html tree to parse.
    :type  soup: BeautifulSoup

    :param table_heading: The table heading to find.
    :type  table_heading: str

    :return: The table under the passed heading as a pandas.DataFrame
    :rtype: pandas.DataFrame

    """

    # Get table html string.
    table_ht = str(soup.find('h3', string=re.compile(table_heading)).find_next())

    try:
        df = read_html(table_ht, index_col=0)[0]
    except:
        print("WARNING: No data found for '"+table_heading+"'. Will return empty DataFrame.")

        df = DataFrame()

    return df
