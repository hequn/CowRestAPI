import base64
import glob
import os
import shutil
import datetime
from inference import Inference
from werkzeug.utils import secure_filename


def get_files(path, top):
    """get the jpg files under the path"""
    if os.path.isdir(path):
        files = glob.glob(path + '*.jpg')
    elif path.find('*') > 0:
        files = glob.glob(path)
    else:
        files = [path]
    if not len(files):
        print('No images found by the given path')
        return []
    return files[0:top]


def get_dir_imgs_number(dir_path):
    allowed_extensions = ['*.png', '*.jpg', '*.jpeg', '*.bmp']
    number = 0
    for e in allowed_extensions:
        number += len(glob.glob(os.path.join(dir_path, e)))
    return number


def max_list(lt):
    """
     Take out the most elements in the list
    :param lt: list
    :return: most elements
    """
    temp = 0
    for i in lt:
        if lt.count(i) > temp:
            max_str = i
            temp = lt.count(i)
    return max_str


def get_predicted_result(predict_images, cid_array):
    """
    TODO: Give the predict here.
    :param predict_images: the images array
    :param cid_array: the oriented type, left center or right : 0,1,2
    :return:
    """
    infer = Inference()
    results = infer.predict(predict_images)
    new_results = []
    new_results1 = []
    for i in results:
        i.sort(reverse=True, key=lambda j: float(j.split(":")[1]))
        new_results.append(i[0].split(":")[0])
        new_results1.append(i[0])
    max_results = max_list(new_results)
    sum = 0
    num = new_results.count(max_results)
    for rid in new_results1:
        if rid.split(":")[0] == max_results:
            sum = sum + float(rid.split(":")[1])
    end_result = round(sum / num, 2)
    return end_result, max_results


def read_image_to_base64(target_images):
    """
    Read the target images to base64 encode and return.
    :param target_images: the array
    :return:
    """
    images_base64_array = []
    for i, name in enumerate(target_images):
        with open(name, 'rb') as f:
            data = f.read()
            encodestr = 'data:image/jpeg;base64,' + base64.b64encode(data).decode()
            index = name.index(".jpg")
            images_base64_array.append({'cid': name[index - 1], 'cvalue': encodestr})
    return images_base64_array


def process_video_to_image(abort, logger, video, folder_path, rfid_code, xvalue, yvalue, width, height):
    """
    Process the video and save the images to the target folder.
    :param video: video file
    :param folder_path:
    :param rfid_code:
    :param xvalue: initial x coordinates
    :param yvalue: initial y coordinates
    :param width: image width
    :param height: image height
    :return: True or False, the executed result
    """
    try:
        import cv2
        vid_cap = cv2.VideoCapture(folder_path + secure_filename(video.filename))
        success, image = vid_cap.read()
        count = 0
        while success:
            vid_cap.set(cv2.CAP_PROP_POS_MSEC, 0.5 * 1000 * count)
            cv2.imwrite(folder_path + rfid_code + "_" + str(count) + "_" + "1" + ".jpg",
                        image[yvalue:yvalue + height, xvalue:xvalue + width])  # save frame as JPEG file
            success, image = vid_cap.read()
            count += 1
        print('Total frames: ', count)
        logger.info("Successful pictures storage from cow rfid_code = {}".format(rfid_code))
    except:
        print("error")
        shutil.rmtree(folder_path)
        logger.error("Failed to store pictures from cow rfid_code = {} , so delete the folder".format(rfid_code))
        abort(501)
        return False
    return True


def insert_record(logger, db_list, db, abort, company_id, rfid_code, folder_path):
    """
     processing for inserting multiple detabase items
    :param db_list: list of data to be processed
    :param db: database
    :param abort: exception handing
    :return: exception or True
    """
    try:
        for db_name in db_list:
            db.session.add(db_name)
        db.session.commit()
    except:
        db.session.rollback()
        shutil.rmtree(folder_path)
        logger.error(
            "cow rfid_code = {} from company_id = {} failed to inserted into the database , so delete the folder".format(
                rfid_code,
                company_id))
        abort(502)
    return True


def verify_param(abort, logger, **kwargs):
    """
     processing of parameter exception
    :param abort: exception keyword
    :param kwargs: parameter dict
    :return: exception or True
    """
    for key in kwargs:
        if kwargs[key] is None or kwargs[key] == "":
            logger.error("{} param not right from method {}".format(key, kwargs["method_name"]))
            return abort(kwargs["error_code"], key)
    return True


def verify_time_param(abort, logger, gather_time1):
    """
     verify gather_time param   eg:"2018-01-01 11:11:11"
    :param abort:
    :param logger:
    :param gather_time:
    :return:  string gather_time
    """
    try:
        gather_time = datetime.datetime.strptime(gather_time1, "%Y-%m-%d %H:%M:%S")
        return gather_time
    except:
        logger.error("gathertime param error from method verfiy")
        abort(400, "gathertime")
