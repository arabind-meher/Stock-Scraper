import os
import re
from time import sleep
from itertools import zip_longest

from tqdm import tqdm
from pandas import DataFrame, concat
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException

from models import Stock
from utils.strings import process_string
from utils.exceptions import DriverNotInitializedError, PageLoadTimeoutError


class StockScraper:
    def __init__(self, directory: str = "data") -> None:
        self.driver = None

        os.makedirs(directory, exist_ok=True)
        self.directory = directory

    def initialize_driver(self, headless: bool = False) -> None:
        options = webdriver.FirefoxOptions()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--private")

        self.driver = webdriver.Firefox(options=options)
        self.driver.maximize_window()
        self.driver.implicitly_wait(10)

    def redirect(self, url: str, wait: float = 1) -> None:
        if not self.driver:
            raise DriverNotInitializedError()

        self.driver.get(url)
        try:
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "title"))
            )
        except TimeoutException:
            raise PageLoadTimeoutError(url)

        sleep(wait)

    def scrape_urls(
        self, urls: list, meta: list = [], file: str = "stocks.csv"
    ) -> None:
        stocks_list = list()

        for url, meta_data in tqdm(
            zip_longest(urls, meta), desc="Stocks:", total=len(urls)
        ):
            stocks_list.append(self.scrape_url(url, meta_data))

        DataFrame(stocks_list).to_csv(os.path.join(self.directory, file))

    def scrape_url(self, url: str, meta: dict, directory: str = "data") -> dict:
        if not self.driver:
            raise DriverNotInitializedError

        self.redirect(url)
        stock = Stock()

        if meta:
            stock.symbol = meta.get("symbol")
            stock.company_name = meta.get("company_name")
            stock.market_cap_category = meta.get("market_cap_category")

            if not stock.market_cap_category:
                raise Exception("Market cap category not found in meta.")

        if not (stock.symbol and stock.company_name):
            heading = re.match(
                r"^(.*?)\s*\((.*?)\)$",
                self.driver.find_element(By.TAG_NAME, "h1").text.strip(),
            )

            if not heading:
                raise Exception("Error while scraping `h1` tag.")

            stock.symbol = heading.group(2)
            stock.company_name = heading.group(1)

        # stock price
        stock.price = self.driver.find_element(By.CLASS_NAME, "text-4xl").text.strip()

        # overview-info
        info_elements = self.driver.find_element(
            By.CSS_SELECTOR, "[data-test='overview-info']"
        ).find_elements(By.TAG_NAME, "tr")

        for element in info_elements:
            key, value = element.find_elements(By.TAG_NAME, "td")
            if key and value:
                stock[process_string(key.text)] = value.text.strip()

        # overview-quotes
        quote_elements = self.driver.find_element(
            By.CSS_SELECTOR, "[data-test='overview-quote']"
        ).find_elements(By.TAG_NAME, "tr")

        for element in quote_elements:
            key, value = element.find_elements(By.TAG_NAME, "td")
            if key and value:
                stock[process_string(key.text)] = value.text.strip()

        # overview-profile
        profile_elements = self.driver.find_element(
            By.CSS_SELECTOR, "[data-test='overview-profile-values']"
        ).find_elements(By.TAG_NAME, "div")

        try:
            stock.industry = (
                profile_elements[0].find_element(By.TAG_NAME, "a").text.strip()
            )
        except NoSuchElementException:
            stock.industry = (
                profile_elements[0].find_elements(By.TAG_NAME, "span")[-1].text.strip()
            )

        try:
            stock.sector = (
                profile_elements[1].find_element(By.TAG_NAME, "a").text.strip()
            )
        except NoSuchElementException:
            stock.sector = (
                profile_elements[1].find_elements(By.TAG_NAME, "span")[-1].text.strip()
            )

        stock.ipo_date = (
            profile_elements[2].find_elements(By.TAG_NAME, "span")[-1].text.strip()
        )
        stock.stock_exchange = (
            profile_elements[4].find_elements(By.TAG_NAME, "span")[-1].text.strip()
        )

        self.scrape_historical_data(url + "history", meta)

        return stock.to_dict()

    def scrape_historical_data(self, url: str, meta: dict):
        if not self.driver:
            raise DriverNotInitializedError

        historical_data_directory = os.path.join(self.directory, "historical_data")
        os.makedirs(historical_data_directory, exist_ok=True)

        self.redirect(url)

        historical_data = list()

        table = self.driver.find_element(By.CLASS_NAME, "svelte-2d4szo")

        columns = [
            process_string(col.text) for col in table.find_elements(By.TAG_NAME, "th")
        ]
        columns.insert(0, "symbol")
        columns.insert(1, "market_cap_category")

        rows = table.find_element(By.TAG_NAME, "tbody").find_elements(By.TAG_NAME, "tr")
        for row in rows:
            row_data = [x.text.strip() for x in row.find_elements(By.TAG_NAME, "td")]
            row_data.insert(0, meta["symbol"])
            row_data.insert(1, meta["market_cap_category"])

            historical_data.append(row_data)

        DataFrame(historical_data, columns=columns).to_csv(
            os.path.join(historical_data_directory, str(meta.get("symbol")) + ".csv"),
            index=False,
        )

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
