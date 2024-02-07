import os
from os.path import basename, dirname, join

from github import Github, UnknownObjectException
from github import InputGitTreeElement
import gitlab
from github.Auth import AppAuthToken


class GitLabToGitHubSync:
    GITLAB_TOKEN = os.environ.get("GITLAB_TOKEN")
    GITLAB_URL = os.environ.get("GITLAB_URL")
    gitlab_client = gitlab.Gitlab(url=GITLAB_URL, private_token=GITLAB_TOKEN, ssl_verify=False)
    PROJECT_ID = os.environ.get("GITLAB_PROJECT_ID")
    project = gitlab_client.projects.get(PROJECT_ID)

    GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
    auth = AppAuthToken(token=GITHUB_TOKEN)
    g = Github(auth=auth)
    repo = g.get_user().get_repo('Uncoder_IO')  # repo name

    @staticmethod
    def __prepare_diff(diff: list):
        for el in diff:
            el_path = el.get("new_path")
            file_name = basename(el_path)
            file_path = join(dirname(__file__), el_path)
            yield {
                "name": file_name,
                "project_path": f"translator/{el_path}",
                "path": file_path,
                "code": el.get("b_mode"),
                "type": "blob"
            }

    def __prepare_gitlab_commit_info(self, commit) -> dict:
        return {
            "author": commit.committer_name,
            "commit_message": commit.message,
            "changes": self.__prepare_diff(commit.diff())
        }

    def __get_gitlab_branch_from_commit(self, commit):
        list_branches = commit.refs()
        try:
            return list_branches[0].get("name")
        except (KeyError, AttributeError):
            return

    def __get_gitlab_commits(self, commit_sha: str):
        origin_commit = self.project.commits.get(commit_sha)
        branch = self.__get_gitlab_branch_from_commit(commit=origin_commit)
        search_parent = True
        parent_ids = origin_commit.parent_ids
        parent_commits = []
        while search_parent:
            for parent_commit_sha in parent_ids:
                parent_commit = self.project.commits.get(parent_commit_sha)
                parent_commit_branch = self.__get_gitlab_branch_from_commit(commit=parent_commit)
                if branch == parent_commit_branch:
                    parent_commits.append(parent_commit)
                    parent_ids.extend(parent_commit.parent_ids)
                else:
                    search_parent = False
                    break
        reversed_parent_commits = list(reversed(parent_commits))
        reversed_parent_commits.append(origin_commit)
        return {
            "branch": branch,
            "commits": [self.__prepare_gitlab_commit_info(commit=c) for c in reversed_parent_commits]
        }

    def create_new_github_branch(self, branch_name: str):
        main_branch_ref = self.repo.get_git_ref('heads/main')
        main_sha = main_branch_ref.object.sha
        return self.repo.create_git_ref(ref=f"refs/heads/{branch_name}", sha=main_sha)

    def checkout_github_branch(self, branch: str):
        try:
            return self.repo.get_git_ref(f'heads/{branch}')
        except UnknownObjectException as err:
            print("Branch not exist. Creating new one...")
            return self.create_new_github_branch(branch_name=branch)

    def push_files_to_github(self, payload: dict, branch: str):
        branch_ref = self.checkout_github_branch(branch=branch)
        branch_sha = branch_ref.object.sha
        base_tree = self.repo.get_git_tree(branch_sha)

        element_list = list()
        for file in payload.get("changes", []):
            with open(file.get("path")) as input_file:
                data = input_file.read()
            element = InputGitTreeElement(
                path=file.get("project_path"),
                mode=file.get("code"),
                type=file.get("type"),
                content=data
            )
            element_list.append(element)

        tree = self.repo.create_git_tree(element_list, base_tree)
        parent = self.repo.get_git_commit(branch_sha)
        commit = self.repo.create_git_commit(payload.get("commit_message"), tree, [parent])
        branch_ref.edit(commit.sha)

    def __get_github_commits(self, branch_name: str):
        branch = self.repo.get_branch(branch=branch_name)
        commit = branch.commit
        return 3

    def run(self, commit_sha: str):
        gitlab_commits_info = self.__get_gitlab_commits(commit_sha=commit_sha)
        github_commits_count = self.__get_github_commits(branch_name=gitlab_commits_info.get("branch"))
        for gitlab_commit_info in gitlab_commits_info.get("commits", [])[github_commits_count:]:
            self.push_files_to_github(payload=gitlab_commit_info, branch=gitlab_commits_info.get("branch"))


if __name__ == "__main__":
    revision_number = 'a47be51cca70b9f397935fbf0ccd6e906620a9b4'
    GitLabToGitHubSync().run(commit_sha=revision_number)

