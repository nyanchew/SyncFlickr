import argparse
import os
import time
import webbrowser

import flickrapi
from dotenv import load_dotenv
from exiftool import ExifToolHelper
from flickrapi import FlickrError

load_dotenv()

# --- 設定情報 ---
FLICKR_API_KEY = os.environ.get('MY_FLICKR_API_KEY')
FLICKR_API_SECRET = os.environ.get('SECRET_KEY')
USERID = os.environ.get('USER_ID')


# Flickrの認証を得る
def flickr_authentication(flickr):
    if not flickr.token_valid(perms='write'):
        flickr.get_request_token(oauth_callback='oob')
        authorize_url = flickr.auth_url(perms='write')
        webbrowser.open_new_tab(authorize_url)
        verifier = str(input('Verifier code: '))
        flickr.get_access_token(verifier)


def update_local_meta_by_flickr_photos(photosetID, local_metadata_map):
    """
    指定されたPhotoset内の写真とその詳細情報を取得する
    """
    try:
        photoset = flickr.photosets.getInfo(photoset_id=photosetID, user_id=USERID)
    except FlickrError as e:
        print(e.args[0])
        return

    print(f"Photoset ID: {photoset['photoset']['title']['_content']} から写真情報を取得中...")
    page = 1
    per_page = 500

    while True:
        try:
            response = flickr.photosets.getPhotos(photoset_id=photosetID, user_id=USERID, page=page)
        except FlickrError as e:
            print(e.args[0])
            break

        current_photos = response['photoset']['photo']
        if not current_photos:
            break
        for photo_summary in current_photos:
            photo_id = photo_summary['id']
            try:
                info_response = flickr.photos.getInfo(photo_id=photo_id)
            except FlickrError as e:
                print(e.args[0])
                time.sleep(30)
                try:
                    info_response = flickr.photos.getInfo(photo_id=photo_id)
                except FlickrError as e:
                    print(e.args[0])
                    continue
            print(f"写真ID: {photo_id} {info_response['photo']['title']['_content']}...")
            exif_response = flickr.photos.getExif(photo_id=photo_id)
            try:
                geo_response = flickr.photos.geo.getLocation(photo_id=photo_id)
            except FlickrError as e:
                print(e.args[0])
                geo_response = None
            if info_response and info_response['photo']:
                photo_info = info_response['photo']
                flickr_photo = {
                    'id': photo_info['id'],
                    'title': photo_info['title']['_content'],
                    'description': photo_info['description']['_content'],
                    'latitude': None,
                    'longitude': None,
                    'altitude': None,
                    'exif': {}
                }

                if geo_response and geo_response['stat'] == 'ok' and 'photo' in geo_response and 'location' in \
                        geo_response['photo']:
                    location = geo_response['photo']['location']
                    flickr_photo['latitude'] = float(location['latitude'])
                    flickr_photo['longitude'] = float(location['longitude'])
                    # Flickrのgeo.getLocationはaltitudeを直接提供しない場合があります。
                    # info_response['photo']['geo']にaltitudeが含まれる場合もありますが、ここではgetExifから取得を試みます。
                    # あるいは、info_response['photo']['location']にaltudeキーがあるか確認します。
                    if 'altitude' in location:
                        flickr_photo['altitude'] = float(location['altitude'])

                if exif_response and exif_response['stat'] == 'ok' and 'photo' in exif_response:
                    for tag in exif_response['photo']['exif']:
                        tagname = tag['tagspace'] + ' ' + tag['tag'] if tag['tagspace'] else tag[
                            'tag']  # FlickrのExifはtagspaceで分類されることがある
                        raw_content = tag.get('raw', {}).get('_content')  # rawがあれば優先
                        clean_content = tag.get('clean', {}).get('_content')  # cleanがあれば次点

                        if tagname == 'XMP-xmpMM PreservedFileName':  # Assuming 'Preserved File Name' might be 'File Name' in Flickr's Exif
                            flickr_photo['exif']['Preserved File Name'] = clean_content or raw_content
                        elif tagname == 'XMP-xmpMM DocumentID':  # Assuming 'Document ID' might be 'DocumentID'
                            flickr_photo['exif']['Document ID'] = clean_content or raw_content
                        elif tagname == 'XMP-xmpMM InstanceID':
                            flickr_photo['exif']['Instance ID'] = clean_content or raw_content
                        elif tagname == 'IFD0 ModifyDate':
                            flickr_photo['exif']['Modify Date'] = clean_content or raw_content
                        # Add other GPS EXIF tags if needed from the CIPA standard, e.g., GPSLatitude, GPSLongitude, GPSAltitude
                        elif tagname == 'GPS GPSLatitudeRef':
                            # This will be string like "35/1, 48/1, 8/1" needing parsing
                            flickr_photo['exif']['GPSLatitude'] = clean_content or raw_content
                        elif tagname == 'GPS GPSLongitudeRef':
                            flickr_photo['exif']['GPSLongitude'] = clean_content or raw_content
                        elif tagname == 'GPS GPSAltitudeRef':
                            flickr_photo['exif']['GPSAltitude'] = clean_content or raw_content

                update_matched_local(flickr_photo, local_metadata_map)
            time.sleep(0.1)  # API呼び出しのレート制限を考慮
        if len(current_photos) < per_page:
            break
        page += 1


def update_matched_local(f_photo, local_metadata_map):
    f_title = f_photo['title']
    f_description = f_photo['description']
    f_preserved_filename = f_photo['exif'].get('Preserved File Name')
    f_document_id = f_photo['exif'].get('Document ID')
    f_instance_id = f_photo['exif'].get('Instance ID')
    f_modify_date = f_photo['exif'].get('Modify Date')
    found_match = False
    matched_file = []
    for l_filepath, l_meta in local_metadata_map.items():
        l_filename_without_ext = os.path.splitext(l_meta['filename'])  # 拡張子なしのファイル名
        # 条件2: FlickrのPreserved File Nameがローカルのファイル名と同じ
        if f_preserved_filename:
            sfilename = os.path.splitext(f_preserved_filename)
            if sfilename[0] == l_filename_without_ext[0]:
                print(f"マッチを検出: Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                matched_file.append(l_filepath)
                found_match = True
            if sfilename[0] + '_Nik_NIK' == l_filename_without_ext[0]:
                print(f"マッチを検出: Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                matched_file.append(l_filepath)
                found_match = True
            if sfilename[0] + '_Nik' == l_filename_without_ext[0] and l_filename_without_ext[1] == '.tif':
                print(f"マッチを検出: Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                matched_file.append(l_filepath)
                found_match = True
        # 条件3: Modify Dateが等しい
        elif f_modify_date and l_meta['modify_date'] and f_modify_date == l_meta['modify_date']:
            print(f"マッチを検出 (Modify Date): Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
            matched_file.append(l_filepath)
            found_match = True

    if not found_match:
        print(f">>>>>Flickr写真 ID {f_photo['id']} (Title: {f_title}) に対応するローカルファイルが見つかりませんでした。")
        return
    if len(matched_file) > 2:
        print(">>>>>3個以上のファイルがマッチ！")
    print("ペアリングされた写真のメタデータをローカルファイルに同期します...")
    for l_filepath in matched_file:
        local_metadata_map.pop(l_filepath)
    # ペアリングされた写真のメタデータをローカルファイルに書き込む
    update_local_file_metadata(matched_file, f_photo)
    time.sleep(0.05)  # ファイル書き込み間の遅延


# --- ローカルファイルメタデータ処理（概念的な関数、実際の実装は選択したライブラリによる） ---
def get_local_file_metadata(filepath):
    """
    ローカルの画像ファイルからメタデータを読み込む
    """
    metadata = {
        'filename': os.path.basename(filepath),
        'modify_date': None,
        'iptc_title': None,
        'iptc_description': None,
        'gps_latitude': None,
        'gps_longitude': None,
        'gps_altitude': None,
    }
    try:
        with ExifToolHelper() as et:
            for d in et.get_metadata(filepath):
                for k, v in d.items():
                    if k == 'EXIF:ModifyDate':
                        metadata['modify_date'] = v
    except Exception as e:
        print(f"  ローカルファイル {filepath} のメタデータ読み込みエラー: {e}")
    return metadata


def update_local_file_metadata(matched_file, flickr_data):
    """
    ローカルの画像ファイルにFlickrのメタデータを書き込む
    """
    try:
        with ExifToolHelper() as et:
            et.set_tags(matched_file, tags={'ImageDescription': flickr_data['title']},
                        params=["-P", "-overwrite_original"])
            et.set_tags(matched_file, tags={'XPComment': flickr_data['description']},
                        params=["-P", "-overwrite_original"])
            # GPS座標の書き込み
            if flickr_data['latitude'] is not None and flickr_data['longitude'] is not None:
                print(f"    GPS座標: ({flickr_data['latitude']}, {flickr_data['longitude']}) を書き込み。")
                et.set_tags(matched_file, tags={'GPSLatitude': flickr_data['latitude'], })
                et.set_tags(matched_file, tags={'GPSLongitude': flickr_data['longitude'], })
                #et.set_tags(matched_file, tags={'GPSAltitude': flickr_data['altitude']})

        print(f"  ローカルファイル {matched_file} のメタデータ更新完了。\n")
    except Exception as e:
        print(f"  ローカルファイル {matched_file} のメタデータ書き込みエラー: {e}\n")


# --- メイン処理 ---
def synchronize_photos(args):
    local_files = []
    for root, _, files in os.walk(args.folder):
        for file in files:
            if file.lower().endswith(('.jpg', '.jpeg', '.tif', '.tiff', '.NEF', '.ORF')):  # 画像ファイルのみを対象
                local_files.append(os.path.join(root, file))
    print(f"ローカルに {len(local_files)} 個の画像ファイルが見つかりました。\n")
    # ローカルファイル情報を事前に読み込む
    local_metadata_map = {}
    counter = 0
    for filepath in local_files:
        counter += 1
        if counter % 10 == 0:
            print("x", end='')
        local_meta = get_local_file_metadata(filepath)
        local_metadata_map[filepath] = local_meta
    update_local_meta_by_flickr_photos(args.photosetID, local_metadata_map)


def parse_arguments():
    parser = argparse.ArgumentParser(description="Synchronize Flickr photoset and local folder.")
    parser.add_argument('photosetID')
    parser.add_argument('folder')
    args = parser.parse_args()
    return args


# --- 実行 ---
if __name__ == "__main__":
    args = parse_arguments()
    flickr = flickrapi.FlickrAPI(FLICKR_API_KEY, FLICKR_API_SECRET, format='parsed-json')
    flickr_authentication(flickr)
    synchronize_photos(args)
