"""
CLI-утилита для запроса данных о требованиях к соискателям с сервиса
поиска работы hh.ru. Основным аргументом является искомая вакансия/должность
(все что выдает сервис по вхождению подстроки запроса в заголовок вакансий).

Второй вариант использования - вывод списка вакансий со ссылками на них
за искомый период.

Примеры:

По умолчанию, программа возвращает словарь требуемых навыков со счетчиком
за указанный период

$ python hh.py python
- все вакансии со словом python в заголовке за количество дней по умолчанию

$ python hh.py "javascript junior" -p 1
- вакансии с "javascript junior" за последний день

$ python hh.py rust --desc
- вакансии rust, учитываются все англоязычные слова в описании
(можно добавить слова в множество exclude, но только часто
встречаемые - сильно сказывается на производительности)

$ python hh.py "junior php" -p 30 -o "stat.txt" --desc
- записать в файл stat.txt навыки вакансий за последние 30 дней
(файл не должен существовать)

$ python hh.py javascript -i 20
- возвратить i самых требуемых навыков

$ python hh.py "маляр" -p 1 --links
- изменить вывод программы - вернуть список записей (id, title, url),
вернуть данные о вакансиях за последний день

"""

import argparse
import concurrent.futures as futures
import json
import os
import re
import ssl
import sys

from collections import Counter
from datetime import datetime
from functools import wraps
from urllib.parse import quote
from urllib.request import Request, urlopen


ARGS = {}
URL_DEFAULTS = {
    'period': 14,
    'area': 1,
    'per_page': 100,
    'text': 'NAME%3A({})',
}

BASE_URL = 'https://api.hh.ru/vacancies/'
HEADERS = {'HH-User-Agent': 'owly_stats'}
METHOD = 'GET'
URL = ''

MAIN_WORKERS = 8
PAGE_WORKERS = 16

BASE_PATH = os.getcwd()
# BASE_PATH = os.path.abspath(os.path.dirname(__file__))

# для подавления предупреждения об отсутсвии ssl сертификата
SSL_CONTEXT = ssl._create_unverified_context()


def _get_response(url):
    request = Request(url, method=METHOD, headers=HEADERS)
    with urlopen(request, context=SSL_CONTEXT) as response:
        return response.read()


def _parse_to_json(bytes_):
    return json.loads(bytes_.decode('utf-8'))


def _from_url(url):
    return _parse_to_json(
        _get_response(url)
    )


def _get_vacancy_data(v_id):
    full_description = _from_url(BASE_URL + v_id)

    if ARGS.links:
        data = _get_title(full_description)
    else:
        data = _parse_skills(full_description)

    return data


def _get_title(json_):
    url_key = json_.get('alternate_url', '...')
    id_ = json_.get('id')
    title = json_.get('name')

    return [(id_, title, url_key)]


def _parse_skills(json_):
    key_skills = json_.get('key_skills', [])
    key_skills = {skill['name'].lower() for skill in key_skills}
    if ARGS.desc:
        description = json_.get('description', '')
        desc_skills = _parse_text(description)
        key_skills.update(desc_skills)

    return list(key_skills)


def _parse_text(text):
    exclude = {
        'ul', 'strong', 'p', 'li', 'br', 'strong',
        'a', 'em', 'ol', 'com', 'io', 'quot', 'quote',
        'junior', 'hr', 'middle', 'teamlead', 'senior',
    }

    skills = set()
    if re.search(r'[а-яА-я]{5}', text):
        parsed = re.findall(r'[a-zA-Z]+', text)
        skills.update(map(str.lower, parsed))
        skills -= exclude
    return skills


def _get_skills(ids):
    with futures.ThreadPoolExecutor(max_workers=PAGE_WORKERS) as executor:
        fs = [executor.submit(_get_vacancy_data, id_) for id_ in ids]
        compl, _ = futures.wait(fs, return_when=futures.ALL_COMPLETED)
        skills = [fs.result() for fs in compl]
    return skills


def _ids_from_page(page_num):
    url = '{}&page={}'.format(URL, page_num)
    page = _from_url(url)
    vacancy_list = page['items']
    return [vacancy['id'] for vacancy in vacancy_list]


def _parse_page(page_num):
    ids = _ids_from_page(page_num)
    skills = _get_skills(ids)
    sk_counter = Counter(sum(skills, []))
    return sk_counter


def _parse_pages(num_pages):
    stat = Counter()

    with futures.ThreadPoolExecutor(max_workers=MAIN_WORKERS) as executor:
        fs = [executor.submit(_parse_page, i) for i in range(num_pages)]
        for future in futures.as_completed(fs):
            try:
                page_counter = future.result()
            except Exception as e:
                print(e)
            else:
                stat.update(page_counter)

    return stat


def _parse_args(ArgumentParser):
    parser = ArgumentParser(
        description=(
            'Returns a summary of key job skills from api '
            'hh.ru containing a "query" in the title'
        ),
        prog='hh',
    )

    parser.add_argument('query', help='query to search')
    parser.add_argument(
        '-p',
        default=URL_DEFAULTS['period'],
        dest='period',
        help='period in days',
        metavar='days (int)',
        type=int,
    )

    parser.add_argument(
        '-i',
        dest='limit',
        help='limit of output skills',
        metavar='skills (int)',
        type=int,
    )

    parser.add_argument(
        '-o',
        dest='file',
        help='output destination (default: sys.stdout)',
        metavar='filename (str)',
        type=str,
    )

    parser.add_argument(
        '--desc',
        help='try to parse vacancy description (EN words)',
        dest='desc',
        default=False,
        action='store_true',
    )

    parser.add_argument(
        '--links',
        help='return vacancies title and link',
        dest='links',
        default=False,
        action='store_true',
    )

    return parser.parse_args()


def _prepare_url(args):
    period = args.period if hasattr(args, 'period') else URL_DEFAULTS['period']
    query = quote(args.query)  # для запросов кириллицей

    params = dict(URL_DEFAULTS)
    params['text'] = params['text'].format(query)
    params['period'] = period
    url = '{}?'.format(BASE_URL)

    params = ['{}={}'.format(k, v) for k, v in params.items()]
    url += '&'.join(params)
    return url


def _prepare_output(raw):
    result = ''
    for pair in raw:
        if ARGS.links:
            result += '{},\n'.format(pair[0])
        else:
            result += '{}: {},\n'.format(*pair)

    return result


def _write_file(dest, output):
    if not os.path.isabs(dest):
        dest = os.path.join(BASE_PATH, dest)
    if os.path.exists(dest):
        print('Specifyed file exists! Choose another name.')
        sys.exit()
    with open(dest, mode='wt', encoding='utf-8') as file:
        file.write(output)


def time_tag(fn):
    """ prints the execution time of the function """
    @wraps(fn)
    def timed(*args, **kwargs):
        time_start = datetime.now()
        result = fn(*args, **kwargs)
        time_end = datetime.now()
        delta = (time_end - time_start).seconds
        print('Time: {} sec'.format(delta))
        return result
    return timed


@time_tag
def main():
    """ program entry point """
    global ARGS
    global URL

    ARGS = _parse_args(argparse.ArgumentParser)
    URL = _prepare_url(ARGS)

    info = _from_url(URL)
    found = info['found']  # общее число найденных вакансий
    num_pages = (info['pages'] + 1)  # включая последнюю страницу

    counter = _parse_pages(num_pages)  # collections.Counter с данными
    limit = ARGS.limit if ARGS.limit else len(counter)
    raw_result = counter.most_common(limit)

    result = _prepare_output(raw_result)
    output = (
        'Vacancies: {}\nArguments: {}\n\n{}'.format(
            found,
            vars(ARGS),
            result
        )
    )

    if ARGS.file:
        _write_file(ARGS.file, output)
    else:
        print(output)


if __name__ == '__main__':
    main()
