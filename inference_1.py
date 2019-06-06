import numpy as np
import importlib
import config
import os
import keras
from sklearn.externals import joblib
from keras import backend as K
from keras.applications.inception_v3 import InceptionV3 as KerasInceptionV3
from keras.layers import GlobalAveragePooling2D, Dense, Input, Embedding, Lambda
from keras.models import Model
import tensorflow as tf


class Inference(object):
    loaded_model = None
    classes_in_keras_format = None
    classes = []
    graph = None
    session = None

    def __init__(self, company_id):
        self.company_id = company_id
        if Inference.classes_in_keras_format is not None:
            return
        self.load_classes()
        Inference.classes_in_keras_format = dict(zip(Inference.classes, range(len(Inference.classes))))
        self.set_img_format()
        Inference.session = tf.Session()
        Inference.graph = tf.get_default_graph()
        # Each Model setting graph and session
        with Inference.graph.as_default():
            with Inference.session.as_default():
                self.create_model()
                self.load_model()

    def preprocess_input(self, i):
        a = []
        for x in i:
            x /= 255.
            x -= 0.5
            x *= 2.
            a.append(x)
        return a

    def predict(self, predict_images):
        with Inference.graph.as_default():
            with Inference.session.as_default():
                predict_images = self.preprocess_input(predict_images)
                out = Inference.loaded_model.predict(np.array(predict_images))
                results = []
                for pred in out:
                    top_indices = pred.argsort()[-3:][::-1]
                    result = [(list(Inference.classes_in_keras_format.keys())[
                                   list(Inference.classes_in_keras_format.values()).index(i)] + ":" + str(
                        "%.2f" % (pred[i] * 100))) for i in top_indices]
                    results.append(result)
                return results

    # def get_model_class_instance(self, *args, **kwargs):
    #     module = importlib.import_module("models.{}".format(Inference.loaded_model))
    #     return module.inst_class(*args, **kwargs)

    def load_classes(self):
        Inference.classes = joblib.load(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         r"{}/classes-inception_v3".format(self.company_id)))

    def get_keras_backend_name(self):
        try:
            return K.backend()
        except AttributeError:
            return K._BACKEND

    def get_input_tensor(self):
        if self.get_keras_backend_name() == 'theano':
            return Input(shape=(3,) + config.img_size)
        else:
            return Input(shape=config.img_size + (3,))

    def create_model(self):
        print("Creating model")
        base_model = KerasInceptionV3(weights='imagenet', include_top=False, input_tensor=self.get_input_tensor())
        # print("base_model.layers:", len(base_model.layers))
        # self.make_net_layers_non_trainable(base_model)
        x = base_model.output
        print(x)
        x = GlobalAveragePooling2D()(x)
        feature = Dense(config.noveltyDetectionLayerSize, activation='elu', name=config.noveltyDetectionLayerName)(x)
        # x = Dropout(0.6)(feature)
        predictions = Dense(len(Inference.classes), activation='softmax', name='predictions')(feature)

        if config.isCenterLoss:
            print(config.isCenterLoss)
            input_target = Input(shape=(None,))
            centers = Embedding(len(Inference.classes), 4096)(input_target)
            print('center:', centers)
            center_loss = Lambda(lambda x: K.sum(K.square(x[0] - x[1][:, 0]), 1, keepdims=True), name='center_loss')(
                [feature, centers])
            model = Model(inputs=[base_model.input, input_target], outputs=[predictions, center_loss])

        elif config.isTripletLoss:
            model = Model(input=base_model.input, output=[predictions, feature])

        else:
            print(base_model.input)
            model = Model(input=base_model.input, output=predictions)
        Inference.loaded_model = model

    def set_img_format(self):
        try:
            if K.backend() == 'theano':
                K.set_image_data_format('channels_first')
            else:
                K.set_image_data_format('channels_last')
        except AttributeError:
            if K._BACKEND == 'theano':
                K.set_image_dim_ordering('th')
            else:
                K.set_image_dim_ordering('tf')

    def load_model(self):
        print("Loading model")
        Inference.loaded_model.load_weights(
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         r"{}/fine-tuned-best-inception_v3-weights.h5".format(
                             self.company_id)))
