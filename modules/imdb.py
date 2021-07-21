import logging, math, re, time
from modules import util
from modules.util import Failed

logger = logging.getLogger("Plex Meta Manager")

builders = ["imdb_list", "imdb_id"]
base_url = "https://www.imdb.com"
urls = {
    "list": f"{base_url}/list/ls",
    "search": f"{base_url}/search/title/?",
    "keyword": f"{base_url}/search/keyword/?"
}

class IMDb:
    def __init__(self, config):
        self.config = config

    def _validate_url(self, imdb_url, language):
        imdb_url = imdb_url.strip()
        if not imdb_url.startswith(urls["list"]) and not imdb_url.startswith(urls["search"]) and not imdb_url.startswith(urls["keyword"]):
            raise Failed(f"IMDb Error: {imdb_url} must begin with either:\n{urls['list']} (For Lists)\n{urls['search']} (For Searches)\n{urls['keyword']} (For Keyword Searches)")
        total, _ = self._total(self._fix_url(imdb_url), language)
        if total > 0:
            return imdb_url
        raise Failed(f"IMDb Error: {imdb_url} failed to parse")

    def validate_imdb_lists(self, imdb_lists, language):
        valid_lists = []
        for imdb_list in util.get_list(imdb_lists, split=False):
            if isinstance(imdb_list, dict):
                dict_methods = {dm.lower(): dm for dm in imdb_list}
                if "url" in dict_methods and imdb_list[dict_methods["url"]]:
                    imdb_url = self._validate_url(imdb_list[dict_methods["url"]], language)
                else:
                    raise Failed("Collection Error: imdb_list attribute url is required")
                if "limit" in dict_methods and imdb_list[dict_methods["limit"]]:
                    list_count = util.regex_first_int(imdb_list[dict_methods["limit"]], "List Limit", default=0)
                else:
                    list_count = 0
            else:
                imdb_url = self._validate_url(str(imdb_list), language)
                list_count = 0
            valid_lists.append({"url": imdb_url, "limit": list_count})
        return valid_lists

    def _fix_url(self, imdb_url):
        if imdb_url.startswith(urls["list"]):
            try:                                list_id = re.search("(\\d+)", str(imdb_url)).group(1)
            except AttributeError:              raise Failed(f"IMDb Error: Failed to parse List ID from {imdb_url}")
            return f"{urls['search']}lists=ls{list_id}"
        elif imdb_url.endswith("/"):
            return imdb_url[:-1]
        else:
            return imdb_url

    def _total(self, imdb_url, language):
        headers = util.header(language)
        if imdb_url.startswith(urls["keyword"]):
            results = self.config.get_html(imdb_url, headers=headers).xpath("//div[@class='desc']/text()")
            total = None
            for result in results:
                if "title" in result:
                    try:
                        total = int(re.findall("(\\d+) title", result)[0])
                        break
                    except IndexError:
                        pass
            if total is None:
                raise Failed(f"IMDb Error: No Results at URL: {imdb_url}")
            return total, 50
        else:
            try:                                results = self.config.get_html(imdb_url, headers=headers).xpath("//div[@class='desc']/span/text()")[0].replace(",", "")
            except IndexError:                  raise Failed(f"IMDb Error: Failed to parse URL: {imdb_url}")
            try:                                total = int(re.findall("(\\d+) title", results)[0])
            except IndexError:                  raise Failed(f"IMDb Error: No Results at URL: {imdb_url}")
            return total, 250

    def _ids_from_url(self, imdb_url, language, limit):
        current_url = self._fix_url(imdb_url)
        total, item_count = self._total(current_url, language)
        headers = util.header(language)
        imdb_ids = []
        if "&start=" in current_url:        current_url = re.sub("&start=\\d+", "", current_url)
        if "&count=" in current_url:        current_url = re.sub("&count=\\d+", "", current_url)
        if "&page=" in current_url:         current_url = re.sub("&page=\\d+", "", current_url)
        if limit < 1 or total < limit:      limit = total

        remainder = limit % item_count
        if remainder == 0:                  remainder = item_count
        num_of_pages = math.ceil(int(limit) / item_count)
        for i in range(1, num_of_pages + 1):
            start_num = (i - 1) * item_count + 1
            util.print_return(f"Parsing Page {i}/{num_of_pages} {start_num}-{limit if i == num_of_pages else i * item_count}")
            if imdb_url.startswith(urls["keyword"]):
                response = self.config.get_html(f"{current_url}&page={i}", headers=headers)
            else:
                response = self.config.get_html(f"{current_url}&count={remainder if i == num_of_pages else item_count}&start={start_num}", headers=headers)
            if imdb_url.startswith(urls["keyword"]) and i == num_of_pages:
                imdb_ids.extend(response.xpath("//div[contains(@class, 'lister-item-image')]//a/img//@data-tconst")[:remainder])
            else:
                imdb_ids.extend(response.xpath("//div[contains(@class, 'lister-item-image')]//a/img//@data-tconst"))
            time.sleep(2)
        util.print_end()
        if imdb_ids:                        return imdb_ids
        else:                               raise Failed(f"IMDb Error: No IMDb IDs Found at {imdb_url}")

    def get_items(self, method, data, language, is_movie):
        pretty = util.pretty_names[method] if method in util.pretty_names else method
        show_ids = []
        movie_ids = []
        fail_ids = []
        def run_convert(imdb_id):
            tvdb_id = self.config.Convert.imdb_to_tvdb(imdb_id) if not is_movie else None
            tmdb_id = self.config.Convert.imdb_to_tmdb(imdb_id) if tvdb_id is None else None
            if tmdb_id:                     movie_ids.append(tmdb_id)
            elif tvdb_id:                   show_ids.append(tvdb_id)
            else:
                logger.error(f"Convert Error: No {'' if is_movie else 'TVDb ID or '}TMDb ID found for IMDb: {imdb_id}")
                fail_ids.append(imdb_id)

        if method == "imdb_id":
            logger.info(f"Processing {pretty}: {data}")
            run_convert(data)
        elif method == "imdb_list":
            status = f"{data['limit']} Items at " if data['limit'] > 0 else ''
            logger.info(f"Processing {pretty}: {status}{data['url']}")
            imdb_ids = self._ids_from_url(data["url"], language, data["limit"])
            total_ids = len(imdb_ids)
            for i, imdb in enumerate(imdb_ids, 1):
                util.print_return(f"Converting IMDb ID {i}/{total_ids}")
                run_convert(imdb)
            logger.info(util.adjust_space(f"Processed {total_ids} IMDb IDs"))
        else:
            raise Failed(f"IMDb Error: Method {method} not supported")
        logger.debug("")
        logger.debug(f"{len(fail_ids)} IMDb IDs Failed to Convert: {fail_ids}")
        logger.debug(f"{len(movie_ids)} TMDb IDs Found: {movie_ids}")
        logger.debug(f"{len(show_ids)} TVDb IDs Found: {show_ids}")
        return movie_ids, show_ids
