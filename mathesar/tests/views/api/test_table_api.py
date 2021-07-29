from unittest.mock import patch
import pytest

from django.core.cache import cache
from django.core.files.base import File, ContentFile
from sqlalchemy import text

from mathesar import reflection
from mathesar.models import Table, DataFile, Schema
from db.tests.types import fixtures
from db import tables


engine_with_types = fixtures.engine_with_types
engine_email_type = fixtures.engine_email_type
temporary_testing_schema = fixtures.temporary_testing_schema


@pytest.fixture
def schema_name():
    return 'table_tests'


@pytest.fixture
def schema(create_schema, schema_name):
    return create_schema(schema_name)


@pytest.fixture
def data_file(csv_filename):
    with open(csv_filename, 'rb') as csv_file:
        data_file = DataFile.objects.create(
            file=File(csv_file),
            created_from='file',
            base_name='patents'
        )
    return data_file


@pytest.fixture
def paste_data_file(paste_filename):
    with open(paste_filename, 'r') as paste_file:
        paste_text = paste_file.read()
    data_file = DataFile.objects.create(
        file=ContentFile(paste_text, name='paste_file.txt'),
        created_from='paste',
        delimiter='\t',
        quotechar='',
        escapechar='',
    )
    return data_file


def check_table_response(response_table, table, table_name):
    assert response_table['id'] == table.id
    assert response_table['name'] == table_name
    assert response_table['schema'] == table.schema.id
    assert 'created_at' in response_table
    assert 'updated_at' in response_table
    assert 'has_dependencies' in response_table
    assert len(response_table['columns']) == len(table.sa_column_names)
    for column in response_table['columns']:
        assert column['name'] in table.sa_column_names
        assert 'type' in column
    assert response_table['records'].startswith('http')
    assert '/api/v0/tables/' in response_table['records']
    assert response_table['records'].endswith('/records/')


def check_table_filter_response(response, status_code=None, count=None):
    response_data = response.json()
    if status_code is not None:
        assert response.status_code == status_code
    if count is not None:
        assert response_data['count'] == count
        assert len(response_data['results']) == count


def _create_table(client, data_files, table_name, schema):
    body = {
        'name': table_name,
        'schema': schema.id,
    }
    if data_files is not None:
        body['data_files'] = [df.id for df in data_files]

    response = client.post('/api/v0/tables/', body)
    response_table = response.json()
    table = Table.objects.get(id=response_table['id'])

    if data_files is not None:
        for df in data_files:
            df.refresh_from_db()

    return response, response_table, table


def _get_expected_name(table_name, data_file=None):
    if not table_name and data_file:
        return data_file.base_name
    elif not table_name and data_file is None:
        return f'Table {Table.objects.count()}'
    else:
        return table_name


def check_create_table_response(client, name, expt_name, data_file, schema):
    num_tables = Table.objects.count()

    response, response_table, table = _create_table(client, [data_file], name, schema)

    first_row = (1, 'NASA Kennedy Space Center', 'Application', 'KSC-12871', '0',
                 '13/033,085', 'Polyimide Wire Insulation Repair System', None)
    column_names = ['Center', 'Status', 'Case Number', 'Patent Number',
                    'Application SN', 'Title', 'Patent Expiration Date']

    assert response.status_code == 201
    assert Table.objects.count() == num_tables + 1
    assert table.get_records()[0] == first_row
    assert all([col in table.sa_column_names for col in column_names])
    assert data_file.table_imported_to.id == table.id
    check_table_response(response_table, table, expt_name)


def test_table_list(create_table, client):
    """
    Desired format:
    {
        "count": 1,
        "results": [
            {
                "id": 1,
                "name": "NASA Table List",
                "schema": "http://testserver/api/v0/schemas/1/",
                "created_at": "2021-04-27T18:43:41.201851Z",
                "updated_at": "2021-04-27T18:43:41.201898Z",
                "columns": [
                    {
                        "name": "mathesar_id",
                        "type": "INTEGER"
                    },
                    {
                        "name": "Center",
                        "type": "VARCHAR"
                    },
                    # etc.
                ],
                "records": "http://testserver/api/v0/tables/3/records/"
            }
        ]
    }
    """
    table_name = 'NASA Table List'
    table = create_table(table_name)

    response = client.get('/api/v0/tables/')
    response_data = response.json()
    response_table = None
    for table_data in response_data['results']:
        if table_data['name'] == table_name:
            response_table = table_data
            break
    assert response.status_code == 200
    assert response_data['count'] >= 1
    assert len(response_data['results']) >= 1
    check_table_response(response_table, table, table_name)


def test_table_list_filter_name(create_table, client):
    expected_tables = {
        'Filter Name 1': create_table('Filter Name 1'),
        'Filter Name 2': create_table('Filter Name 2'),
        'Filter Name 3': create_table('Filter Name 3')
    }

    filter_tables = ['Filter Name 1', 'Filter Name 2']
    query_str = ','.join(filter_tables)
    response = client.get(f'/api/v0/tables/?name={query_str}')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=2)

    response_tables = {res['name']: res for res in response_data['results']}
    for table_name in filter_tables:
        assert table_name in response_tables
        table = expected_tables[table_name]
        response_table = response_tables[table_name]
        check_table_response(response_table, table, table_name)


def test_table_list_filter_schema(create_table, client):
    expected_tables = {
        'Schema 1': create_table('Filter Schema 1', schema='Schema 1'),
        'Schema 2': create_table('Filter Schema 2', schema='Schema 2'),
        'Schema 3': create_table('Filter Schema 3', schema='Schema 3')
    }

    filter_tables = ['Schema 2', 'Schema 3']
    query_str = ','.join(filter_tables)
    response = client.get(f'/api/v0/tables/?schema={query_str}')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=2)

    response_tables = {Schema.objects.get(id=res['schema']).name: res
                       for res in response_data['results']}
    for schema_name in filter_tables:
        assert schema_name in response_tables
        table = expected_tables[schema_name]
        response_table = response_tables[schema_name]
        check_table_response(response_table, table, table.name)


@pytest.mark.parametrize('timestamp_type', ['created', 'updated'])
def test_table_list_filter_timestamps(create_table, client, timestamp_type):
    table_name = f'Fitler {timestamp_type}'
    table = create_table(table_name)
    query_str = '2020-01-01 8:00'

    response = client.get(f'/api/v0/tables/?{timestamp_type}_before={query_str}')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=0)

    response = client.get(f'/api/v0/tables/?{timestamp_type}_after={query_str}')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=1)
    check_table_response(response_data['results'][0], table, table_name)

    timestamp = table.created_at if timestamp_type == 'created' else table.updated_at
    response = client.get(f'/api/v0/tables/?{timestamp_type}={timestamp}')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=1)
    check_table_response(response_data['results'][0], table, table_name)


def test_table_list_filter_import_verified(create_table, client):
    expected_tables = {
        True: create_table('Filter Verified 1'),
        False: create_table('Filter Verified 2'),
    }
    for verified, table in expected_tables.items():
        table.import_verified = verified
        table.save()

    for verified, table in expected_tables.items():
        query_str = str(verified).lower()
        response = client.get(f'/api/v0/tables/?import_verified={query_str}')
        response_data = response.json()
        check_table_filter_response(response, status_code=200, count=1)
        check_table_response(response_data['results'][0], table, table.name)


def test_table_list_filter_imported(create_table, client):
    expected_tables = {
        None: create_table('Filter Imported 1'),
        False: create_table('Filter Imported 2'),
        True: create_table('Filter Imported 3'),
    }
    for verified, table in expected_tables.items():
        table.import_verified = verified
        table.save()

    response = client.get('/api/v0/tables/?not_imported=false')
    check_table_filter_response(response, status_code=200, count=2)

    table = expected_tables[None]
    response = client.get('/api/v0/tables/?not_imported=true')
    response_data = response.json()
    check_table_filter_response(response, status_code=200, count=1)
    check_table_response(response_data['results'][0], table, table.name)


def test_table_detail(create_table, client):
    """
    Desired format:
    One item in the results list in the table list view, see above.
    """
    table_name = 'NASA Table Detail'
    table = create_table(table_name)

    response = client.get(f'/api/v0/tables/{table.id}/')
    response_table = response.json()
    assert response.status_code == 200
    check_table_response(response_table, table, table_name)


def test_table_type_suggestion(client, schema, engine_email_type):
    table_name = 'Type Inference Table'
    file = 'mathesar/tests/data/type_inference.csv'
    with open(file, 'rb') as csv_file:
        data_file = DataFile.objects.create(file=File(csv_file))

    body = {
        'data_files': [data_file.id],
        'name': table_name,
        'schema': schema.id,
    }
    response_table = client.post('/api/v0/tables/', body).json()
    table = Table.objects.get(id=response_table['id'])

    EXPECTED_TYPES = {
        'col_1': 'NUMERIC',
        'col_2': 'BOOLEAN',
        'col_3': 'BOOLEAN',
        'col_4': 'VARCHAR',
        'col_5': 'VARCHAR',
        'col_6': 'NUMERIC'
    }
    response = client.get(f'/api/v0/tables/{table.id}/type_suggestions/')
    response_table = response.json()
    assert response.status_code == 200
    assert response_table == EXPECTED_TYPES


@pytest.mark.parametrize('table_name', ['Test Table Create From Datafile', ''])
def test_table_create_from_datafile(client, data_file, schema, table_name):
    expt_name = _get_expected_name(table_name, data_file=data_file)
    check_create_table_response(client, table_name, expt_name, data_file, schema)


@pytest.mark.parametrize('table_name', ['Test Table Create From Paste', ''])
def test_table_create_from_paste(client, schema, paste_data_file, table_name):
    expt_name = _get_expected_name(table_name)
    check_create_table_response(client, table_name, expt_name, paste_data_file, schema)


@pytest.mark.parametrize('data_files', [None, []])
@pytest.mark.parametrize('table_name', ['test_table_no_file', ''])
def test_table_create_without_datafile(client, schema, data_files, table_name):
    num_tables = Table.objects.count()
    expt_name = _get_expected_name(table_name)

    response, response_table, table = _create_table(
        client, data_files, table_name, schema
    )

    assert response.status_code == 201
    assert Table.objects.count() == num_tables + 1
    assert len(table.sa_columns) == 1  # only the internal `mathesar_id` column
    assert len(table.get_records()) == 0
    check_table_response(response_table, table, expt_name)


def test_table_create_name_taken(client, paste_data_file, schema, create_table, schema_name):
    create_table('Table 2', schema=schema_name)
    create_table('Table 3', schema=schema_name)
    expt_name = 'Table 4'
    check_create_table_response(client, '', expt_name, paste_data_file, schema)


def test_table_create_base_name_taken(client, data_file, schema, create_table, schema_name):
    create_table('patents', schema=schema_name)
    create_table('patents 1', schema=schema_name)
    expt_name = 'patents 2'
    check_create_table_response(client, '', expt_name, data_file, schema)


def test_table_partial_update(create_table, client):
    table_name = 'NASA Table Partial Update'
    new_table_name = 'NASA Table Partial Update New'
    table = create_table(table_name)

    body = {'name': new_table_name}
    response = client.patch(f'/api/v0/tables/{table.id}/', body)

    response_table = response.json()
    assert response.status_code == 200
    check_table_response(response_table, table, new_table_name)

    table = Table.objects.get(oid=table.oid)
    assert table.name == new_table_name


def test_table_delete(create_table, client):
    table_name = 'NASA Table Delete'
    table = create_table(table_name)
    table_count = len(Table.objects.all())

    with patch.object(tables, 'delete_table') as mock_infer:
        response = client.delete(f'/api/v0/tables/{table.id}/')
    assert response.status_code == 204

    # Ensure the Django model was deleted
    new_table_count = len(Table.objects.all())
    assert table_count - 1 == new_table_count

    # Ensure the backend table would have been deleted
    assert mock_infer.call_args is not None
    assert mock_infer.call_args[0] == (
        table.name,
        table.schema.name,
        table.schema._sa_engine,
    )
    assert mock_infer.call_args[1] == {
        'cascade': True
    }


def test_table_dependencies(client, create_table):
    table_name = 'NASA Table Dependencies'
    table = create_table(table_name)

    response = client.get(f'/api/v0/tables/{table.id}/')
    response_table = response.json()
    assert response.status_code == 200
    assert response_table['has_dependencies'] is True


def test_table_404(client):
    response = client.get('/api/v0/tables/3000/')
    assert response.status_code == 404
    assert response.json()['detail'] == 'Not found.'


def test_table_type_suggestion_404(client):
    response = client.get('/api/v0/tables/3000/type_suggestions/')
    assert response.status_code == 404
    assert response.json()['detail'] == 'Not found.'


def test_table_create_from_datafile_404(client):
    body = {
        'data_files': [-999],
        'name': 'test_table',
        'schema': -999,
    }
    response = client.post('/api/v0/tables/', body)
    response_table = response.json()
    assert response.status_code == 400
    assert 'object does not exist' in response_table['schema'][0]
    assert 'object does not exist' in response_table['data_files'][0]


def test_table_create_from_multiple_datafile(client, data_file, schema):
    body = {
        'data_files': [data_file.id, data_file.id],
        'name': 'test_table',
        'schema': schema.id,
    }
    response = client.post('/api/v0/tables/', body)
    response_table = response.json()
    assert response.status_code == 400
    assert response_table['data_files'][0] == 'Multiple data files are unsupported.'


def test_table_partial_update_invalid_field(create_table, client):
    table_name = 'NASA Table Partial Update'
    table = create_table(table_name)

    body = {'schema': table.schema.id}
    response = client.patch(f'/api/v0/tables/{table.id}/', body)

    assert response.status_code == 400
    assert 'is not supported' in response.json()['schema']


def test_table_partial_update_404(client):
    response = client.patch('/api/v0/tables/3000/', {})
    assert response.status_code == 404
    assert response.json()['detail'] == 'Not found.'


def test_table_delete_404(client):
    response = client.delete('/api/v0/tables/3000/')
    assert response.status_code == 404
    assert response.json()['detail'] == 'Not found.'


def test_table_update(client, create_table):
    table = create_table('update_table_test')
    response = client.put(f'/api/v0/tables/{table.id}/')
    assert response.status_code == 405
    assert response.json()['detail'] == 'Method "PUT" not allowed.'


def test_table_get_with_reflect_new(client, table_for_reflection):
    _, table_name, _ = table_for_reflection
    cache.clear()
    response = client.get('/api/v0/tables/')
    # The table number should only change after the GET request
    response_data = response.json()
    actual_created = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    assert len(actual_created) == 1
    created_table = actual_created[0]
    assert created_table['name'] == table_name
    created_columns = created_table['columns']
    assert created_columns == [
        {'name': 'id', 'type': 'INTEGER'}, {'name': 'name', 'type': 'VARCHAR'}
    ]


def test_table_get_with_reflect_column_change(client, table_for_reflection):
    schema_name, table_name, engine = table_for_reflection
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    orig_created = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    orig_id = orig_created[0]['id']
    new_column_name = 'new_name'
    with engine.begin() as conn:
        conn.execute(
            text(f'ALTER TABLE {schema_name}.{table_name} RENAME COLUMN name TO {new_column_name};')
        )
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    altered_table = [
        table for table in response_data['results'] if table['name'] == table_name
    ][0]
    new_columns = altered_table['columns']
    assert altered_table['id'] == orig_id
    assert new_columns == [
        {'name': 'id', 'type': 'INTEGER'},
        {'name': new_column_name, 'type': 'VARCHAR'}
    ]


def test_table_get_with_reflect_name_change(client, table_for_reflection):
    schema_name, table_name, engine = table_for_reflection
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    orig_created = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    orig_id = orig_created[0]['id']
    new_table_name = 'super_new_table_name'
    with engine.begin() as conn:
        conn.execute(
            text(
                f'ALTER TABLE {schema_name}.{table_name} RENAME TO {new_table_name};'
            )
        )
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    orig_created_2 = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    assert len(orig_created_2) == 0
    modified = [
        table for table in response_data['results'] if table['name'] == new_table_name
    ]
    modified_id = modified[0]['id']
    assert len(modified) == 1
    assert orig_id == modified_id


def test_table_get_with_reflect_delete(client, table_for_reflection):
    schema_name, table_name, engine = table_for_reflection
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    orig_created = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    assert len(orig_created) == 1
    with engine.begin() as conn:
        conn.execute(text(f'DROP TABLE {schema_name}.{table_name};'))
    cache.clear()
    response = client.get('/api/v0/tables/')
    response_data = response.json()
    new_created = [
        table for table in response_data['results'] if table['name'] == table_name
    ]
    assert len(new_created) == 0


def test_table_viewset_sets_cache(client):
    cache.delete(reflection.DB_REFLECTION_KEY)
    assert not cache.get(reflection.DB_REFLECTION_KEY)
    client.get('/api/v0/schemas/')
    assert cache.get(reflection.DB_REFLECTION_KEY)


def test_table_viewset_checks_cache(client):
    cache.delete(reflection.DB_REFLECTION_KEY)
    with patch.object(reflection, 'reflect_tables_from_schema') as mock_reflect:
        client.get('/api/v0/tables/')
    mock_reflect.assert_called()
