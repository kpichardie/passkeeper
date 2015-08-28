#!/usr/bin/env python
# -*- coding: utf-8 -*-

import base as test_base
import passkeeper
from passkeeper import Passkeeper
from mock import patch, call, mock_open, MagicMock, Mock

class PasskeeperTestCase(test_base.TestCase):

    @patch('passkeeper.Git')
    def setUp(self, mock_git):
        super(PasskeeperTestCase, self).setUp()
        self.getpass_orig = passkeeper.getpass
        passkeeper.getpass = MagicMock()
        passkeeper.getpass.return_value = "secret"
        self.mock_git = mock_git
        self.pk = Passkeeper('foo')

    def tearDown(self):
        super(PasskeeperTestCase, self).tearDown()
        del self.pk
        del self.mock_git
        passkeeper.getpass = self.getpass_orig

    def test_constructor(self):
        self.mock_git.assert_called_once_with('foo')
        self.assertEquals(self.pk.directory, 'foo')
        self.assertEquals(self.pk.encrypted_dir, 'encrypted')


    @patch('passkeeper.Passkeeper.cleanup_ini')
    @patch('passkeeper.Passkeeper.encrypt')
    @patch('passkeeper.create_dir')
    def test_init_dir(self, mock_create_dir, mock_encrypt, mock_cleanup):
        self.mock_git.reset_mock()
        with patch('__builtin__.open', mock_open(), create=True) as file_mock:
            file_handle = file_mock()
            self.pk.init_dir()

        calls = [call().init(), call().add_gitignore(['*.ini', '/*.raw'])]
        self.mock_git.assert_has_calls(calls)

        calls = [call().create_dir(['foo', 'foo/default.raw'])]
        self.mock_create_dir.assert_has_calls(calls)

        file_mock.assert_called_with('foo/default.ini', 'w')
        file_mock.assert_called_with('foo/default.raw/ssh_id.rsa', 'w')
        self.assertEquals(True, file_handle.write.called)

        mock_encrypt.assert_called_once_with()
        mock_cleanup.assert_called_once_with()


    @patch('passkeeper.Passkeeper._remove_old_encrypted_files')
    @patch('passkeeper.run_cmd')
    @patch('passkeeper.os.listdir')
    @patch('passkeeper.os.path.isfile')
    def test_cleanup_ini(self, mock_isfile, mock_listdir, mock_cmd,
                               mock_remove_old_encrypted_files):
        # One ignored file and one valid file
        mock_listdir.return_value = ['ignored', 'bar.ini']
        mock_isfile.return_value = True
        self.pk.cleanup_ini()

        mock_cmd.assert_called_once_with('shred --remove foo/bar.ini')
        mock_remove_old_encrypted_files.assert_called_once_with()

        # Test with bad filepath. Do nothing
        mock_cmd.reset_mock()
        mock_listdir.return_value = ['bar.ini']
        mock_isfile.return_value = False
        self.pk.cleanup_ini()

        self.assertEquals(mock_cmd.call_count, 0)


    @patch('passkeeper.raw_input')
    @patch('passkeeper.run_cmd')
    @patch('passkeeper.os.listdir')
    @patch('passkeeper.os.path.isfile')
    def test__remove_old_encrypted_files(self, mock_isfile, mock_listdir,
                               mock_cmd, mock_raw_input):
        # One file and 3 in encrypted so delete one.
        # Basicly the script will remove 2 file.
        # But we will cancel one of them
        #  * bar keep
        #  * foo delete canceled
        #  * bar deleted


        mock_raw_input.side_effect = ['n', 'y']
        mock_listdir.return_value = [ 'bar.ini.passkeeper',
                                      'foo.ini.passkeeper',
                                      'bli.ini.passkeeper']
        mock_isfile.side_effect = [ True, False, False ]
        self.pk._remove_old_encrypted_files()

        mock_cmd.assert_called_once_with('shred --remove foo/encrypted/bli.ini.passkeeper')
        calls = [ call().soft_remove(['encrypted/bli.ini.passkeeper']),
                  call().commit('Remove file encrypted/bli.ini.passkeeper')]
        self.mock_git.assert_has_calls(calls)



    @patch('passkeeper.decrypt')
    @patch('passkeeper.os.listdir')
    @patch('passkeeper.os.path.isfile')
    def test_decrypt(self, mock_isfile, mock_listdir, mock_decrypt):
        # One ignored file and one valid file
        mock_listdir.return_value = ['ignored', 'bar.ini.passkeeper']
        mock_isfile.return_value = True
        self.pk.decrypt()

        mock_decrypt.assert_called_once_with(passphrase='secret',
                                 source='foo/encrypted/bar.ini.passkeeper',
                                 output='foo/bar.ini')

        # Test with bad filepath. Do nothing
        mock_decrypt.reset_mock()
        mock_listdir.return_value = ['bar.ini.passkeeper']
        mock_isfile.return_value = False
        self.pk.decrypt()

        self.assertEquals(mock_decrypt.call_count, 0)


    @patch('passkeeper.create_dir')
    @patch('passkeeper.encrypt')
    @patch('passkeeper.os.listdir')
    @patch('passkeeper.os.path.isfile')
    def test_encrypt(self, mock_isfile, mock_listdir, mock_encrypt, mock_create_dir):
        # Wrong confirmation password
        orig_getpass = passkeeper.getpass
        passkeeper.getpass = Mock()
        passkeeper.getpass.side_effect = ['secret', 'secret_typo']

        self.assertFalse(self.pk.encrypt())
        passkeeper.getpass = orig_getpass

        # One ignored file and one valid file
        mock_encrypt.reset_mock()
        self.mock_git.reset_mock()
        mock_listdir.return_value = ['ignored', 'bar.ini']
        mock_isfile.return_value = True
        self.assertTrue(self.pk.encrypt(commit_message='my message'))

        mock_create_dir.assert_called_once_with('foo/encrypted')
        mock_encrypt.assert_called_once_with(passphrase='secret',
                                    source='foo/bar.ini',
                                    output='foo/encrypted/bar.ini.passkeeper')
        calls = [call().add(['encrypted/bar.ini.passkeeper']), call().commit('my message')]
        self.mock_git.assert_has_calls(calls)
        

        # Test with bad filepath. Don't encrypt this file
        mock_encrypt.reset_mock()
        self.mock_git.reset_mock()
        mock_listdir.return_value = ['bar.ini']
        mock_isfile.return_value = False

        self.assertTrue(self.pk.encrypt())
        self.assertEquals(mock_encrypt.call_count, 0)


    @patch('passkeeper.ConfigParser.RawConfigParser')
    @patch('passkeeper.os.listdir')
    @patch('passkeeper.os.path.isfile')
    def test_search(self, mock_isfile, mock_listdir, mock_rawconfig):
        # One ignored file and one valid file
        # In this file we have 4 sections :
        # - one matching in section name
        # - one matching not matching at all
        # - one matching with value content
        mock_config = MagicMock()
        mock_config.sections.return_value = ['unmatched', 'WanTed', 'value']
        vals = {('unmatched',): [('foo', 'bar')],
                ('WanTed',): [('foo', 'bar')],
                ('value',): [('found', '.wanted.')]}
        def side_effect(*args):
            return vals[args]
        mock_config.items = MagicMock(side_effect=side_effect)
        mock_rawconfig.return_value = mock_config
        mock_listdir.return_value = ['ignored', 'bar.ini']
        mock_isfile.return_value = True
        config, matching_sections = self.pk.search(pattern='WANTED')

        mock_config.read.assert_called_once_with('foo/bar.ini')
        self.assertEquals(['WanTed', 'value'], matching_sections)

        # Test with bad filepath.
        mock_config = Mock()
        mock_config.sections.return_value = []
        mock_rawconfig.return_value = mock_config
        mock_listdir.return_value = ['bar.ini']
        mock_isfile.return_value = False
        config, matching_sections = self.pk.search(pattern='WANTED')

        self.assertEquals(mock_config.read.call_count, 0)
        self.assertEquals([], matching_sections)


    @patch('passkeeper.shred_dir')
    def test_flush_history(self, mock_shred):

        self.pk.flush_history()

        mock_shred.assert_called_once_with('foo/.git')
        calls = [ call().init(),
                  call().add(['encrypted', '.gitignore']),
                  call().commit('Clean git History')]

        self.mock_git.assert_has_calls(calls)
