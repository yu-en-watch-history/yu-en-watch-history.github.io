import os
import json
import requests
from typing import Dict, Any, List, Optional
from collections import defaultdict

NOTION_API_VERSION = "2022-06-28"
NOTION_API_URL = "https://api.notion.com/v1"

def fetch_notion_database_items(notion_token: str, database_id: str) -> List[Dict[str, Any]]:
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": NOTION_API_VERSION,
        "Content-Type": "application/json"
    }
    url = f"{NOTION_API_URL}/databases/{database_id}/query"
    items = []
    has_more = True
    start_cursor = None
    
    while has_more:
        payload = {"page_size": 100}
        if start_cursor:
            payload["start_cursor"] = start_cursor
            
        res = requests.post(url, headers=headers, json=payload, timeout=30)
        res.raise_for_status()
        data = res.json()
        items.extend(data.get("results", []))
        has_more = data.get("has_more", False)
        start_cursor = data.get("next_cursor")
        
    return items

def extract_property_value(page: Dict[str, Any], prop_name: str, prop_type: str) -> Any:
    props = page.get("properties", {})
    prop = props.get(prop_name, {})
    if prop_type == "title":
        title_list = prop.get("title", [])
        return "".join([t.get("plain_text", "") for t in title_list]).strip()
    elif prop_type == "rich_text":
        text_list = prop.get("rich_text", [])
        return "".join([t.get("plain_text", "") for t in text_list]).strip() or None
    elif prop_type == "number":
        return prop.get("number")
    elif prop_type == "checkbox":
        return prop.get("checkbox", False)
    elif prop_type == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    return None

def fetch_tmdb_metadata(title: str, year: Optional[int], api_key: str) -> Dict[str, Any]:
    if not api_key:
        return {}
    search_url = "https://api.themoviedb.org/3/search/movie"
    params = {"api_key": api_key, "query": title, "language": "zh-TW"}
    if year:
        params["primary_release_year"] = year
    try:
        r = requests.get(search_url, params=params, timeout=10)
        r.raise_for_status()
        results = r.json().get("results", [])
        if not results and year:
            params.pop("primary_release_year", None)
            r = requests.get(search_url, params=params, timeout=10)
            results = r.json().get("results", [])
        if not results:
            return {}
        top_match = results[0]
        tmdb_id = top_match.get("id")
        poster_path = top_match.get("poster_path")
        backdrop_path = top_match.get("backdrop_path")
        ext_url = f"https://api.themoviedb.org/3/movie/{tmdb_id}/external_ids"
        ext_res = requests.get(ext_url, params={"api_key": api_key}, timeout=10)
        imdb_id = ext_res.json().get("imdb_id") if ext_res.ok else None
        return {
            "tmdbId": tmdb_id,
            "posterPath": poster_path,
            "backdropPath": backdrop_path,
            "imdbId": imdb_id
        }
    except Exception as e:
        print(f"Warning: Failed to fetch TMDb for '{title}': {e}")
        return {}

def sync_notion_to_movies_json(notion_token: str, database_id: str, movies_json_path: str, tmdb_api_key: Optional[str] = None):
    existing_movies = []
    lookup_by_title = {}
    lookup_by_imdb = {}
    known_series_groups = {} # seriesName -> seriesGroupPosition
    max_id = 0
    max_group_pos = 0
    
    if os.path.exists(movies_json_path):
        with open(movies_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            existing_movies = data.get("movies", [])
            for m in existing_movies:
                m_id = m.get("id", 0)
                if isinstance(m_id, int) and m_id > max_id:
                    max_id = m_id
                if m.get("title"):
                    lookup_by_title[m["title"].strip()] = m
                if m.get("imdbId"):
                    lookup_by_imdb[m["imdbId"].strip()] = m
                s_name = m.get("seriesName")
                g_pos = m.get("seriesGroupPosition")
                if s_name and g_pos is not None:
                    known_series_groups[s_name.strip()] = g_pos
                    if g_pos > max_group_pos:
                        max_group_pos = g_pos
                        
    notion_pages = fetch_notion_database_items(notion_token, database_id)
    if not notion_pages:
        print("Notice: Notion database is empty. Preserving existing movies.json.")
        return
        
    next_id = max_id + 1
    next_group_pos = max_group_pos + 1
    
    # Raw parsed items
    raw_year_items = defaultdict(list)    # releaseYear -> list of item dicts
    raw_series_items = defaultdict(list)  # seriesName -> list of item dicts
    
    for page in notion_pages:
        title = extract_property_value(page, "片名", "title")
        if not title:
            continue
            
        release_year = extract_property_value(page, "上映年份", "number")
        section = extract_property_value(page, "分類", "select") or "year"
        watched = extract_property_value(page, "已觀看", "checkbox")
        favorite = extract_property_value(page, "喜愛", "checkbox")
        disliked = extract_property_value(page, "按爛", "checkbox")
        series_name = extract_property_value(page, "系列名稱", "rich_text")
        series_pos = extract_property_value(page, "系列順序", "number")
        year_pos = extract_property_value(page, "年度順序", "number")
        imdb_id = extract_property_value(page, "IMDb ID", "rich_text")
        
        old_movie = lookup_by_title.get(title) or (lookup_by_imdb.get(imdb_id) if imdb_id else None)
        
        if old_movie:
            movie_id = old_movie.get("id")
            poster_path = old_movie.get("posterPath")
            backdrop_path = old_movie.get("backdropPath")
            imdb_rating = old_movie.get("imdbRating")
            imdb_vote_count = old_movie.get("imdbVoteCount")
            imdb_updated_at = old_movie.get("imdbUpdatedAt")
            favorite_photo_paths = old_movie.get("favoritePhotoPaths", [])
            final_imdb_id = imdb_id or old_movie.get("imdbId")
            if release_year is None:
                release_year = old_movie.get("releaseYear")
            if year_pos is None:
                year_pos = old_movie.get("sourcePosition")
            if series_pos is None:
                series_pos = old_movie.get("seriesPosition")
            if not series_name:
                series_name = old_movie.get("seriesName")
        else:
            movie_id = next_id
            next_id += 1
            tmdb_meta = fetch_tmdb_metadata(title, release_year, tmdb_api_key) if tmdb_api_key else {}
            poster_path = tmdb_meta.get("posterPath")
            backdrop_path = tmdb_meta.get("backdropPath")
            final_imdb_id = imdb_id or tmdb_meta.get("imdbId")
            imdb_rating = None
            imdb_vote_count = None
            imdb_updated_at = None
            favorite_photo_paths = []
            
        base_item = {
            "id": movie_id,
            "title": title,
            "releaseYear": release_year,
            "section": section,
            "watched": watched,
            "favorite": favorite,
            "disliked": disliked,
            "seriesName": series_name,
            "seriesPositionRaw": series_pos if series_pos is not None else 9999,
            "yearPositionRaw": year_pos if year_pos is not None else 9999,
            "imdbId": final_imdb_id,
            "posterPath": poster_path,
            "backdropPath": backdrop_path,
            "favoritePhotoPaths": favorite_photo_paths,
            "imdbRating": imdb_rating,
            "imdbVoteCount": imdb_vote_count,
            "imdbUpdatedAt": imdb_updated_at
        }
        
        if section == "series" and series_name:
            raw_series_items[series_name.strip()].append(base_item)
        else:
            y = release_year or 0
            raw_year_items[y].append(base_item)
            
    final_movies = []
    
    # 1. Process Year section (sorted by releaseYear descending, then yearPositionRaw ascending)
    sorted_years = sorted(raw_year_items.keys(), reverse=True)
    for y in sorted_years:
        items = raw_year_items[y]
        items.sort(key=lambda x: (x["yearPositionRaw"], x["title"]))
        
        for norm_pos, item in enumerate(items, start=1):
            source_key = f"year-{y}-{norm_pos}"
            item_out = {
                "id": item["id"],
                "sourceKey": source_key,
                "title": item["title"],
                "releaseYear": item["releaseYear"],
                "section": "year",
                "watched": item["watched"],
                "favorite": item["favorite"],
                "disliked": item["disliked"],
                "sourcePosition": norm_pos,
                "seriesName": None,
                "seriesOrderLabel": None,
                "seriesPosition": None,
                "seriesGroupPosition": None,
                "imdbId": item["imdbId"],
                "posterPath": item["posterPath"],
                "backdropPath": item["backdropPath"],
                "favoritePhotoPaths": item["favoritePhotoPaths"],
                "imdbRating": item["imdbRating"],
                "imdbVoteCount": item["imdbVoteCount"],
                "imdbUpdatedAt": item["imdbUpdatedAt"]
            }
            final_movies.append(item_out)
            
    # 2. Process Series section
    series_keys = list(raw_series_items.keys())
    series_groups_ordered = sorted(
        series_keys,
        key=lambda s: known_series_groups.get(s, 999999)
    )
    
    for s_name in series_groups_ordered:
        group_pos = known_series_groups.get(s_name)
        if group_pos is None:
            group_pos = next_group_pos
            next_group_pos += 1
            known_series_groups[s_name] = group_pos
            
        items = raw_series_items[s_name]
        items.sort(key=lambda x: (x["seriesPositionRaw"], x["releaseYear"] or 0, x["title"]))
        
        for norm_pos, item in enumerate(items, start=1):
            source_key = f"series-{group_pos}-{norm_pos}"
            item_out = {
                "id": item["id"],
                "sourceKey": source_key,
                "title": item["title"],
                "releaseYear": item["releaseYear"],
                "section": "series",
                "watched": item["watched"],
                "favorite": item["favorite"],
                "disliked": item["disliked"],
                "sourcePosition": None,
                "seriesName": s_name,
                "seriesOrderLabel": str(norm_pos),
                "seriesPosition": norm_pos,
                "seriesGroupPosition": group_pos,
                "imdbId": item["imdbId"],
                "posterPath": item["posterPath"],
                "backdropPath": item["backdropPath"],
                "favoritePhotoPaths": item["favoritePhotoPaths"],
                "imdbRating": item["imdbRating"],
                "imdbVoteCount": item["imdbVoteCount"],
                "imdbUpdatedAt": item["imdbUpdatedAt"]
            }
            final_movies.append(item_out)
            
    # 3. Save output
    output_data = {"movies": final_movies}
    with open(movies_json_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)
    print(f"Successfully processed and normalized {len(final_movies)} movies.")

if __name__ == "__main__":
    notion_token = os.getenv("NOTION_TOKEN")
    database_id = os.getenv("NOTION_DATABASE_ID")
    movies_path = os.getenv("MOVIES_JSON_PATH", "movies.json")
    tmdb_key = os.getenv("TMDB_API_KEY")
    if not notion_token or not database_id:
        print("Error: Missing NOTION_TOKEN or NOTION_DATABASE_ID.")
        exit(1)
    sync_notion_to_movies_json(notion_token, database_id, movies_path, tmdb_key)
