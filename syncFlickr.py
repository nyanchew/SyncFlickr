import argparse
import locale
import os
import sys
import time
import webbrowser
import exiftool

import flickrapi
from dotenv import load_dotenv
from flickrapi import FlickrError
from exiftool import ExifToolHelper

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

def get_flickr_photos_in_photoset(photosetID, local_metadata_map):
    """
    指定されたPhotoset内の写真とその詳細情報を取得する
    """
    photoset = flickr.photosets.getInfo(photoset_id=photosetID, user_id=USERID)

    print(f"Photoset ID: {photoset['photoset']['title']['_content']} から写真情報を取得中...")
    page = 1
    per_page = 500

    while True:
        response = flickr.photosets.getPhotos(photoset_id=photosetID, user_id=USERID, page=page)
#            {"photoset_id": photoset_id, "extras": "description,geo,tags,url_o,original_format,date_upload",
#             "per_page": per_page, "page": page}
#        )
        if not response or 'photoset' not in response:
            break

        current_photos = response['photoset']['photo']
        if not current_photos:
            break

        for photo_summary in current_photos:
            photo_id = photo_summary['id']
            print(f"写真ID: {photo_id} の詳細情報を取得中...")
            info_response = flickr.photos.getInfo(photo_id=photo_id)
            exif_response = flickr.photos.getExif(photo_id=photo_id)
            try:
                geo_response = flickr.photos.geo.getLocation(photo_id=photo_id)
            except FlickrError:
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
                        elif tagname == 'DocumentID':  # Assuming 'Document ID' might be 'DocumentID'
                            flickr_photo['exif']['Document ID'] = clean_content or raw_content
                        # Add other GPS EXIF tags if needed from the CIPA standard, e.g., GPSLatitude, GPSLongitude, GPSAltitude
                        elif tagname == 'GPS GPSLatitude':
                            # This will be string like "35/1, 48/1, 8/1" needing parsing
                            flickr_photo['exif']['GPSLatitude'] = clean_content or raw_content
                        elif tagname == 'GPS GPSLongitude':
                            flickr_photo['exif']['GPSLongitude'] = clean_content or raw_content
                        elif tagname == 'GPS GPSAltitude':
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
        found_match = False
        matched_file = []
        for l_filepath, l_meta in local_metadata_map.items():
            l_filename_without_ext = os.path.splitext(l_meta['filename'])  # 拡張子なしのファイル名
            # 条件1: FlickrのPreserved File Nameがローカルのファイル名と同じ
            if f_preserved_filename:
                sfilename = os.path.splitext(f_preserved_filename)
                if sfilename[0] == l_filename_without_ext[0]:
                    print(f"マッチを検出 (Preserved File Name): Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                    matched_file.append(l_filepath)
                    found_match = True
                if sfilename[0]+'_Nik_NIK' == l_filename_without_ext[0]:
                    print(f"マッチを検出 (Preserved File Name): Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                    matched_file.append(l_filepath)
                    found_match = True
                if sfilename[0]+'_Nik' == l_filename_without_ext[0] and l_filename_without_ext[1] == '.tif':
                    print(f"マッチを検出 (Preserved File Name): Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                    matched_file.append(l_filepath)
                    found_match = True

            # 条件2: FlickrのDocument IDがローカルのDocument IDと同じ
            # ローカルファイルのDocument IDは、ExifまたはXMPから読み取る必要があります。
            # ここではダミーの実装になっています。
            if f_document_id and l_meta['document_id'] and f_document_id == l_meta['document_id']:
                print(f"マッチを検出 (Document ID): Flickr ID {f_photo['id']} とファイル {l_meta['filename']}")
                found_match = True

        if not found_match:
            print(f"Flickr写真 ID {f_photo['id']} (Title: {f_title}) に対応するローカルファイルが見つかりませんでした。")
            return
        print("\nペアリングされた写真のメタデータをローカルファイルに同期します...")
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
        'document_id': None,  # ローカルファイルのDocument ID
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
                    if k == 'Document ID':
                        metadata['document_id'] = v

        # exif_data = read_exif(filepath)
        # metadata['document_id'] = exif_data.get('Document ID') # 仮のキー名
        # iptc_data = read_iptc(filepath)
        # metadata['iptc_title'] = iptc_data.get('Title') # 仮のキー名
        # metadata['iptc_description'] = iptc_data.get('Description') # 仮のキー名
        # gps_info = get_gps(filepath)
        # metadata['gps_latitude'] = gps_info.get('latitude')
        # metadata['gps_longitude'] = gps_info.get('longitude')
        # metadata['gps_altitude'] = gps_info.get('altitude')

        print(f"  ローカルファイル {metadata['filename']} メタデータ取得完了。")
    except Exception as e:
        print(f"  ローカルファイル {filepath} のメタデータ読み込みエラー: {e}")
    return metadata

def update_local_file_metadata(matched_file, flickr_data):
    """
    ローカルの画像ファイルにFlickrのメタデータを書き込む
    """
    #print(f"  ローカルファイル {os.path.basename(filepath)} にFlickrデータを書き込み中...")
    try:
        with ExifToolHelper() as et:
            et.set_tags(matched_file, tags={'ImageDescription': flickr_data['title']},
                        params=["-P", "-overwrite_original"])
            et.set_tags(matched_file, tags={'IPTC:title': flickr_data['title']},
                        params=["-P", "-overwrite_original"])
            et.set_tags(matched_file, tags={'IPTC:description': flickr_data['description']},
                        params=["-P", "-overwrite_original"])
        # IPTC Titleへの書き込み
        # write_iptc(filepath, 'Title', flickr_data['title'])
        # IPTC Descriptionへの書き込み
        # write_iptc(filepath, 'Description', flickr_data['description'])

        # GPS座標の書き込み
        if flickr_data['latitude'] is not None and flickr_data['longitude'] is not None:
            # set_gps(filepath, flickr_data['latitude'], flickr_data['longitude'], flickr_data['altitude'])
            print(f"    GPS座標: ({flickr_data['latitude']}, {flickr_data['longitude']}) を書き込み予定。")
        else:
            print("    FlickrデータにGPS座標がありません。")

        print(f"  ローカルファイル {os.path.basename(filepath)} のメタデータ更新完了。")
    except Exception as e:
        print(f"  ローカルファイル {filepath} のメタデータ書き込みエラー: {e}")


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
    for filepath in local_files:
       local_meta = get_local_file_metadata(filepath)
       local_metadata_map[filepath] = local_meta

    flickr_photos = get_flickr_photos_in_photoset(args.photosetID, local_metadata_map)
    if not flickr_photos:
        print("Flickr Photosetから写真が取得できませんでした。")
        return
    print(f"\nFlickrから {len(flickr_photos)} 枚の写真を取得しました。")





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
