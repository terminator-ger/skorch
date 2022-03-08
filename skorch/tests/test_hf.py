"""Tests for hf.py"""

import difflib
import pickle
from contextlib import contextmanager
from copy import deepcopy

import numpy as np
import pytest
import torch
from sklearn.base import clone


SPECIAL_TOKENS = ["[UNK]", "[CLS]", "[SEP]", "[PAD]", "[MASK]"]


def text_similarity(text1, text2):
    """Very simple text similarity function"""
    def process(text):
        text = text.replace(' ', '').replace('##', '').lower().strip()
        return text

    diffs = list(difflib.Differ().compare(process(text1), process(text2)))
    same = sum(diff.startswith(' ') for diff in diffs)
    total = len(diffs)
    return same / total


@contextmanager
def temporary_set_param(obj, key, val):
    """Temporarily set value

    Avoid permanently mutating the object. This way, the object does not need to
    be re-initialized.

    """
    val_before = obj.get_params()[key]
    try:
        obj.set_params(**{key: val})
        yield
    finally:
        obj.set_params(**{key: val_before})


class _HuggingfaceTokenizersBaseTest:
    """Base class for testing huggingface tokenizer transformers

    Should implement a (parametrized) ``tokenizer`` fixture.

    Tests should not call ``fit`` since that can be expensive for pretrained
    tokenizers. Instead, implement these tests on the subclass if necessary.

    """
    @pytest.fixture(scope='module')
    def data(self):
        return [
            "The Zen of Python, by Tim Peters",
            "Beautiful is better than ugly.",
            "Explicit is better than implicit.",
            "Simple is better than complex.",
            "Complex is better than complicated.",
            "Flat is better than nested.",
            "Sparse is better than dense.",
            "Readability counts.",
            "Special cases aren't special enough to break the rules.",
            "Although practicality beats purity.",
            "Errors should never pass silently.",
            "Unless explicitly silenced.",
            "In the face of ambiguity, refuse the temptation to guess.",
            "There should be one-- and preferably only one --obvious way to do it.",
            "Although that way may not be obvious at first unless you're Dutch.",
            "Now is better than never.",
            "Although never is often better than *right* now.",
            "If the implementation is hard to explain, it's a bad idea.",
            "If the implementation is easy to explain, it may be a good idea.",
            "Namespaces are one honking great idea -- let's do more of those!",
        ]

    def test_transform(self, tokenizer, data):
        Xt = tokenizer.transform(data)
        assert 'input_ids' in Xt
        assert 'attention_mask' in Xt

        for val in Xt.values():
            assert val.shape[0] == len(data)
            assert val.shape[1] == tokenizer.max_length
            assert isinstance(val, torch.Tensor)

    def test_inverse_transform(self, tokenizer, data):
        # Inverse transform does not necessarily result in the exact same
        # output; therefore, we test text similarity.
        Xt = tokenizer.transform(data)
        Xt_inv = tokenizer.inverse_transform(Xt)
        cutoff = 0.9
        for x_orig, x_dec, x_other in zip(data, Xt_inv, data[1:]):
            # check that original and inverse transform are similar
            assert text_similarity(x_orig, x_dec) > cutoff
            assert text_similarity(x_orig, x_other) < cutoff

    def test_vocabulary(self, tokenizer):
        assert isinstance(tokenizer.vocabulary_, dict)

        # vocabulary size is not always exactly as indicated
        vocab_size = pytest.approx(len(tokenizer.vocabulary_), abs=10)
        assert vocab_size == tokenizer.fast_tokenizer_.vocab_size

    def test_get_feature_names(self, tokenizer):
        feature_names = tokenizer.get_feature_names()
        assert isinstance(feature_names, list)
        assert isinstance(feature_names[0], str)

    def test_keys_in_output(self, tokenizer, data):
        Xt = tokenizer.transform(data)

        assert len(Xt) == 2
        assert 'input_ids' in Xt
        assert 'attention_mask' in Xt

    def test_return_token_type_ids(self, tokenizer, data):
        with temporary_set_param(tokenizer, 'return_token_type_ids', True):
            Xt = tokenizer.transform(data)

        assert 'token_type_ids' in Xt

    def test_return_length(self, tokenizer, data):
        with temporary_set_param(tokenizer, 'return_length', True):
            Xt = tokenizer.transform(data)

        assert 'length' in Xt

    def test_return_attention_mask(self, tokenizer, data):
        with temporary_set_param(tokenizer, 'return_attention_mask', False):
            Xt = tokenizer.transform(data)

        assert 'attention_mask' not in Xt

    @pytest.mark.parametrize('return_tensors', [None, str])
    def test_return_lists(self, tokenizer, data, return_tensors):
        with temporary_set_param(tokenizer, 'return_tensors', return_tensors):
            Xt = tokenizer.transform(data)

        assert set(Xt) == {'input_ids', 'attention_mask'}
        for val in Xt.values():
            assert isinstance(val, list)
            assert isinstance(val[0], list)

        # input type ids can have different lengths because they're not padded
        # or truncated
        assert len(set(len(row) for row in Xt['input_ids'])) != 1

    def test_numpy_arrays(self, tokenizer, data):
        with temporary_set_param(tokenizer, 'return_tensors', 'np'):
            Xt = tokenizer.transform(data)

        assert 'input_ids' in Xt
        assert 'attention_mask' in Xt

        for val in Xt.values():
            assert val.shape[0] == len(data)
            assert val.shape[1] == tokenizer.max_length
            assert isinstance(val, np.ndarray)

    def test_pickle(self, tokenizer):
        # does not raise
        pickled = pickle.dumps(tokenizer)
        pickle.loads(pickled)

    def test_deepcopy(self, tokenizer):
        deepcopy(tokenizer)  # does not raise

    def test_clone(self, tokenizer):
        clone(tokenizer)  # does not raise


class TestHuggingfaceTokenizer(_HuggingfaceTokenizersBaseTest):
    from tokenizers import Tokenizer
    from tokenizers.models import BPE, WordLevel, WordPiece, Unigram
    from tokenizers import normalizers
    from tokenizers import pre_tokenizers
    from tokenizers.normalizers import Lowercase, NFD, StripAccents
    from tokenizers.pre_tokenizers import Whitespace, Digits
    from tokenizers.processors import ByteLevel, TemplateProcessing
    from tokenizers.trainers import BpeTrainer, UnigramTrainer
    from tokenizers.trainers import WordPieceTrainer, WordLevelTrainer

    # Test one of the main tokenizer types: BPE, WordLevel, WordPiece, Unigram.
    # Individual settings like vocab size or choice of pre_tokenizer may not
    # necessarily make sense.
    settings = {
        'setting0': {
            'tokenizer': Tokenizer(BPE(unk_token="[UNK]")),
            'trainer': BpeTrainer(
                vocab_size=50, special_tokens=SPECIAL_TOKENS, show_progress=False
            ),
            'normalizer': None,
            'pre_tokenizer': Whitespace(),
            'post_processor': ByteLevel(),
            'max_length': 100,
        },
        'setting1': {
            'tokenizer': Tokenizer(WordLevel(unk_token="[UNK]")),
            'trainer': WordLevelTrainer(
                vocab_size=100, special_tokens=SPECIAL_TOKENS, show_progress=False
            ),
            'normalizer': Lowercase(),
            'pre_tokenizer': Whitespace(),
            'post_processor': None,
            'max_length': 100,
        },
        'setting2': {
            'tokenizer': Tokenizer(WordPiece(unk_token="[UNK]")),
            'trainer': WordPieceTrainer(
                vocab_size=150, special_tokens=SPECIAL_TOKENS, show_progress=False
            ),
            'normalizer': normalizers.Sequence([NFD(), Lowercase(), StripAccents()]),
            'pre_tokenizer': pre_tokenizers.Sequence(
                [Whitespace(), Digits(individual_digits=True)]
            ),
            'post_processor': TemplateProcessing(
                single="[CLS] $A [SEP]",
                pair="[CLS] $A [SEP] $B:1 [SEP]:1",
                special_tokens=[("[CLS]", 1), ("[SEP]", 2)],
            ),
            'max_length': 200,
        },
        'setting4': {
            'tokenizer': Tokenizer(Unigram()),
            'trainer': UnigramTrainer(
                vocab_size=120, special_tokens=SPECIAL_TOKENS, show_progress=False
            ),
            'normalizer': None,
            'pre_tokenizer': None,
            'post_processor': None,
            'max_length': 250,
        },
    }

    @pytest.fixture(params=settings.keys())
    def tokenizer(self, request, data):
        # return one tokenizer per setting
        from skorch.hf import HuggingfaceTokenizer

        return HuggingfaceTokenizer(**self.settings[request.param]).fit(data)

    @pytest.mark.xfail
    def test_clone(self, tokenizer):
        # This might get fixed in a future release of tokenizers
        # https://github.com/huggingface/tokenizers/issues/941
        clone(tokenizer)  # does not raise

    def test_pickle_and_fit(self, tokenizer, data):
        # This might get fixed in a future release of tokenizers
        # https://github.com/huggingface/tokenizers/issues/941
        pickled = pickle.dumps(tokenizer)
        loaded = pickle.loads(pickled)
        msg = "Tried to fit HuggingfaceTokenizer but trainer is None"
        with pytest.raises(TypeError, match=msg):
            loaded.fit(data)

    def test_pad_token(self, tokenizer, data):
        pad_token = "=FOO="
        tokenizer.set_params(pad_token=pad_token)
        tokenizer.fit(data)
        Xt = tokenizer.transform(['hello there'])
        pad_token_id = Xt['input_ids'][0, -1].item()
        assert tokenizer.vocabulary_[pad_token] == pad_token_id

    def test_fit_with_numpy_array(self, tokenizer, data):
        # does not raise
        tokenizer.fit(np.array(data))

    def test_fit_with_generator(self, tokenizer, data):
        # does not raise
        tokenizer.fit(row for row in data)

    def test_fit_str_raises(self, tokenizer, data):
        msg = r"Iterable over raw text documents expected, string object received"
        with pytest.raises(ValueError, match=msg):
            tokenizer.fit(data[0])


class TestHuggingfacePretrainedTokenizer(_HuggingfaceTokenizersBaseTest):
    @pytest.fixture(scope='module')
    def tokenizer(self, data):
        # return one tokenizer per setting
        from skorch.hf import HuggingfacePretrainedTokenizer

        return HuggingfacePretrainedTokenizer('bert-base-cased').fit(data)